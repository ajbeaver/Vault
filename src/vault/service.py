from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from vault.address_book import AddressBookManager, normalize_address
from vault.config import (
    DEFAULT_PROFILES,
    NotFoundError,
    VaultError,
    ValidationError,
    load_json,
    path_is_within_git_worktree,
    resolve_paths,
    resolve_root_home,
    save_json,
    set_active_profile_name,
)
from vault.evm import EVMClient, format_units
from vault.journal import JournalManager, normalize_tx_hash
from vault.keystore import KeystoreManager, copy_account_file, now_iso
from vault.monitor import MonitorStateManager
from vault.networks import NetworkManager, copy_network_record
from vault.policy import PolicyManager
from vault.signers import resolve_signer
from vault.themes import DEFAULT_THEME_NAME, normalize_theme_name, theme_rows


MAINNET_CHAIN_IDS = {1, 10, 137, 8453, 42161}
MAX_MONITOR_CACHE = 200


class VaultService:
    def __init__(self, home: str | None = None, profile: str | None = None) -> None:
        self.home_arg = home
        self.paths = resolve_paths(home=home, profile=profile)

    @property
    def profile_name(self) -> str:
        return self.paths.profile_name

    def list_profiles(self) -> dict[str, Any]:
        rows = []
        for profile_name in DEFAULT_PROFILES:
            paths = resolve_paths(home=self.home_arg, profile=profile_name)
            rows.append(
                {
                    "name": profile_name,
                    "is_active": profile_name == self.profile_name,
                    "storage_path": str(paths.home),
                    "uses_legacy_home": paths.using_legacy_profile_home,
                    "has_data": self._profile_has_data(paths),
                }
            )
        return {
            "summary": f"Found {len(rows)} profile(s)",
            "active_profile": self.profile_name,
            "profiles": rows,
        }

    def show_profile(self) -> dict[str, Any]:
        config = load_json(self.paths.config_file, {})
        return {
            "summary": f"Current profile is {self.profile_name}",
            "name": self.profile_name,
            "storage_path": str(self.paths.home),
            "uses_legacy_home": self.paths.using_legacy_profile_home,
            "default_account": config.get("default_account"),
            "default_network": load_json(self.paths.networks_file, {"default_network": None}).get("default_network"),
        }

    def context_summary(self) -> dict[str, Any]:
        accounts_payload = self._accounts().list_accounts()
        networks_payload = self._networks().list_networks()
        config = load_json(self.paths.config_file, {})
        default_account_name = accounts_payload.get("default_account")
        default_network_name = networks_payload.get("default_network")
        default_account = next(
            (item for item in accounts_payload["accounts"] if item["name"] == default_account_name),
            None,
        )
        default_network = next(
            (item for item in networks_payload["networks"] if item["name"] == default_network_name),
            None,
        )
        safety = self.safety_status()
        has_safety_issues = bool(safety["findings"] and safety["findings"][0] != "No immediate safety issues detected.")
        return {
            "summary": f"Context for {self.profile_name}",
            "profile": self.profile_name,
            "is_protected_profile": self.profile_name == "prod",
            "default_account": default_account,
            "default_network": default_network,
            "account_count": accounts_payload["count"],
            "network_count": networks_payload["count"],
            "theme": normalize_theme_name(config.get("theme", DEFAULT_THEME_NAME)),
            "safety_state": "warning" if has_safety_issues else "ok",
            "safety_findings": safety["findings"],
        }

    def use_profile(self, name: str) -> dict[str, Any]:
        root_home = resolve_root_home(self.home_arg)
        set_active_profile_name(root_home, name)
        self.paths = resolve_paths(home=self.home_arg, profile=name)
        return {
            "summary": f"Active profile set to {self.profile_name}",
            "name": self.profile_name,
            "storage_path": str(self.paths.home),
            "uses_legacy_home": self.paths.using_legacy_profile_home,
        }

    def list_themes(self) -> dict[str, Any]:
        active = self.show_theme()["name"]
        rows = theme_rows(active)
        return {
            "summary": f"Found {len(rows)} theme(s)",
            "profile": self.profile_name,
            "active_theme": active,
            "themes": rows,
            "count": len(rows),
        }

    def show_theme(self) -> dict[str, Any]:
        config = load_json(self.paths.config_file, {})
        name = normalize_theme_name(config.get("theme", DEFAULT_THEME_NAME))
        rows = {row["name"]: row for row in theme_rows(name)}
        theme = rows[name]
        return {
            "summary": f"Current theme is {name}",
            "profile": self.profile_name,
            "name": name,
            "textual_theme": theme["textual_theme"],
            "description": theme["description"],
        }

    def use_theme(self, name: str) -> dict[str, Any]:
        config = load_json(self.paths.config_file, {})
        config["theme"] = normalize_theme_name(name)
        save_json(self.paths.config_file, config)
        return self.show_theme()

    def create_account(self, name: str, passphrase: str, set_default: bool = False) -> dict[str, Any]:
        payload = self._accounts().create_account(name, passphrase, set_default=set_default)
        payload["profile"] = self.profile_name
        return payload

    def add_watch_only_account(self, name: str, address: str, set_default: bool = False) -> dict[str, Any]:
        payload = self._accounts().add_watch_only_account(name, address, set_default=set_default)
        payload["profile"] = self.profile_name
        return payload

    def import_account(
        self,
        name: str,
        private_key_hex: str,
        passphrase: str,
        set_default: bool = False,
    ) -> dict[str, Any]:
        payload = self._accounts().import_account(name, private_key_hex, passphrase, set_default=set_default)
        payload["profile"] = self.profile_name
        return payload

    def list_accounts(self) -> dict[str, Any]:
        payload = self._accounts().list_accounts()
        payload["profile"] = self.profile_name
        return payload

    def use_account(self, name: str) -> dict[str, Any]:
        payload = self._accounts().set_default_account(name)
        payload["profile"] = self.profile_name
        return payload

    def add_network(self, name: str, rpc_url: str, chain_id: int, symbol: str, set_default: bool = False) -> dict[str, Any]:
        payload = self._networks().add_network(name, rpc_url, chain_id, symbol, set_default=set_default)
        payload["profile"] = self.profile_name
        return payload

    def add_alchemy_network(
        self,
        preset: str,
        api_key_env: str,
        name: str | None = None,
        set_default: bool = False,
    ) -> dict[str, Any]:
        payload = self._networks().add_alchemy_network(preset, api_key_env, name=name, set_default=set_default)
        payload["profile"] = self.profile_name
        return payload

    def add_anvil_network(
        self,
        name: str = "local",
        rpc_url: str = "http://127.0.0.1:8545",
        chain_id: int = 31337,
        symbol: str = "ETH",
        set_default: bool = False,
    ) -> dict[str, Any]:
        payload = self._networks().add_anvil_network(
            name=name,
            rpc_url=rpc_url,
            chain_id=chain_id,
            symbol=symbol,
            set_default=set_default,
        )
        payload["profile"] = self.profile_name
        return payload

    def list_networks(self) -> dict[str, Any]:
        payload = self._networks().list_networks()
        payload["profile"] = self.profile_name
        return payload

    def list_network_presets(self) -> dict[str, Any]:
        return self._networks().list_presets()

    def use_network(self, name: str) -> dict[str, Any]:
        payload = self._networks().set_default_network(name)
        payload["profile"] = self.profile_name
        return payload

    def list_address_book(self) -> dict[str, Any]:
        payload = self._address_book().list_entries()
        payload["profile"] = self.profile_name
        return payload

    def add_address_book_entry(
        self,
        name: str,
        address: str,
        network_scope: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        payload = self._address_book().add_entry(name, address, network_scope=network_scope, notes=notes)
        payload["profile"] = self.profile_name
        return payload

    def remove_address_book_entry(self, name: str) -> dict[str, Any]:
        payload = self._address_book().remove_entry(name)
        payload["profile"] = self.profile_name
        return payload

    def list_journal(self) -> dict[str, Any]:
        payload = self._journal().list_entries()
        payload["profile"] = self.profile_name
        return payload

    def show_journal_entry(self, entry_id: str) -> dict[str, Any]:
        payload = self._journal().get_entry(entry_id)
        payload["profile"] = self.profile_name
        return payload

    def show_receipt(self, tx_hash: str, network_name: str | None = None) -> dict[str, Any]:
        journal_entry = None
        try:
            journal_entry = self._journal().get_entry(tx_hash)
        except VaultError:
            journal_entry = None
        effective_network = network_name or (journal_entry or {}).get("network")
        if not effective_network:
            raise ValidationError("Network is required when the transaction is not present in the local journal.")
        network = self._networks().get_network(effective_network)
        receipt = EVMClient(network).get_transaction_receipt(tx_hash)
        try:
            self._journal().attach_receipt(tx_hash, receipt)
        except VaultError:
            pass
        return {
            "summary": f"Receipt for {receipt['transaction_hash']}",
            "profile": self.profile_name,
            **receipt,
        }

    def verify_backup(self, account_name: str, passphrase: str) -> dict[str, Any]:
        signer = self._resolve_signer(account_name)
        if not signer.can_sign:
            raise ValidationError(f"Account `{account_name}` is watch-only and has no encrypted keystore to verify.")
        signer.accounts.unlock_account(account_name, passphrase)
        return {
            "summary": f"Verified backup material for {account_name}",
            "profile": self.profile_name,
            "account_name": account_name,
            "address": signer.address,
            "signer_type": signer.signer_type,
        }

    def sign_message(self, account_name: str | None, passphrase: str, message: str) -> dict[str, Any]:
        signer = self._resolve_signer(account_name)
        payload = signer.sign_message(passphrase, message)
        payload["profile"] = self.profile_name
        return payload

    def sign_typed_data(self, account_name: str | None, passphrase: str, typed_data: dict[str, Any]) -> dict[str, Any]:
        signer = self._resolve_signer(account_name)
        payload = signer.sign_typed_data(passphrase, typed_data)
        payload["profile"] = self.profile_name
        return payload

    def list_policies(self) -> dict[str, Any]:
        payload = self._policies().list_policies()
        payload["profile"] = self.profile_name
        return payload

    def show_policy(self, account_name: str | None = None) -> dict[str, Any]:
        payload = self._policies().show_effective_policy(account_name)
        payload["profile"] = self.profile_name
        return payload

    def set_policy_rule(self, rule: str, value: str, account_name: str | None = None) -> dict[str, Any]:
        payload = self._policies().set_rule(rule, value, account_name)
        payload["profile"] = self.profile_name
        return payload

    def unset_policy_rule(self, rule: str, account_name: str | None = None) -> dict[str, Any]:
        payload = self._policies().unset_rule(rule, account_name)
        payload["profile"] = self.profile_name
        return payload

    def explain_policy_action(
        self,
        account_name: str | None,
        network_name: str | None,
        recipient: str,
        amount: str,
        token_address: str | None = None,
    ) -> dict[str, Any]:
        account = self._resolve_account_metadata(account_name)
        network = self._networks().get_network(network_name)
        recipient_entry = self._address_book().resolve(recipient, network["name"])
        evaluation = self._policies().evaluate_action(
            account_name=account["name"],
            network_name=network["name"],
            recipient_address=recipient_entry["address"],
            asset_type="erc20" if token_address else "native",
            amount=amount,
            token_address=token_address,
            protected=requires_strong_confirmation(self.profile_name, network),
        )
        evaluation["profile"] = self.profile_name
        evaluation["account_name"] = account["name"]
        evaluation["network_name"] = network["name"]
        evaluation["recipient_name"] = recipient_entry["name"]
        evaluation["recipient_address"] = recipient_entry["address"]
        evaluation["asset_type"] = "erc20" if token_address else "native"
        evaluation["amount"] = amount
        evaluation["token_address"] = token_address
        return evaluation

    def doctor(self, network_name: str | None = None) -> dict[str, Any]:
        network = self._networks().get_network(network_name)
        payload = EVMClient(network).doctor()
        payload["profile"] = self.profile_name
        return payload

    def balance(
        self,
        account_name: str | None = None,
        network_name: str | None = None,
        token_address: str | None = None,
    ) -> dict[str, Any]:
        account = self._resolve_account_metadata(account_name)
        network = self._networks().get_network(network_name)
        client = EVMClient(network)
        payload = (
            client.get_token_balance(account["address"], token_address)
            if token_address
            else client.get_native_balance(account["address"])
        )
        payload["profile"] = self.profile_name
        payload["account_name"] = account["name"]
        return payload

    def contract_read(
        self,
        target: str,
        function_name: str,
        abi_file: str | None = None,
        abi_fragment: str | None = None,
        args_json: str | None = None,
        network_name: str | None = None,
    ) -> dict[str, Any]:
        network = self._networks().get_network(network_name)
        resolved = self._resolve_lookup_target(target, network["name"])
        abi, abi_source, abi_reference = self._load_abi(abi_file=abi_file, abi_fragment=abi_fragment)
        args = self._parse_args_json(args_json)
        payload = EVMClient(network).get_contract_read(
            address=resolved["address"],
            abi=abi,
            function_name=function_name,
            args=args,
        )
        payload.update(
            {
                "summary": f"Contract read for {payload['address']} on {network['name']}",
                "profile": self.profile_name,
                "network": network["name"],
                "chain_id": network["chain_id"],
                "query": resolved["query"],
                "query_kind": resolved["query_kind"],
                "abi_source": abi_source,
                "abi_reference": abi_reference,
                "function": function_name,
                "args": args,
            }
        )
        return payload

    def preview_contract_write(
        self,
        from_account_name: str,
        target: str,
        function_name: str,
        abi_file: str | None = None,
        abi_fragment: str | None = None,
        args_json: str | None = None,
        value: str | None = None,
        network_name: str | None = None,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        account = self._resolve_account_metadata(from_account_name)
        network = self._networks().get_network(network_name)
        resolved = self._resolve_lookup_target(target, network["name"])
        abi, abi_source, abi_reference = self._load_abi(abi_file=abi_file, abi_fragment=abi_fragment)
        args = self._parse_args_json(args_json)
        prepared = EVMClient(network).prepare_contract_write(
            from_address=account["address"],
            contract_address=resolved["address"],
            abi=abi,
            function_name=function_name,
            args=args,
            value=value,
            nonce=nonce,
            gas_limit=gas_limit,
            gas_price_gwei=gas_price_gwei,
            max_fee_per_gas_gwei=max_fee_per_gas_gwei,
            max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
        )
        query_name = resolved["query"] if resolved["query_kind"] != "raw" else None
        details = {
            "kind": "contract_write",
            "query": resolved["query"],
            "query_kind": resolved["query_kind"],
            "abi_source": abi_source,
            "abi_reference": abi_reference,
            "contract_function": function_name,
            "args": args,
            "value": prepared["value"],
            "value_wei": prepared["value_wei"],
        }
        return self._finalize_prepared_transaction(
            prepared=prepared,
            account=account,
            network=network,
            query=resolved["query"],
            query_kind=resolved["query_kind"],
            recipient_name=query_name,
            action="contract_write",
            details=details,
            policy_asset_type="contract",
            policy_amount=prepared["value"],
            policy_token_address=None,
        )

    def simulate_contract_write(
        self,
        from_account_name: str,
        target: str,
        function_name: str,
        abi_file: str | None = None,
        abi_fragment: str | None = None,
        args_json: str | None = None,
        value: str | None = None,
        network_name: str | None = None,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        preview = self.preview_contract_write(
            from_account_name=from_account_name,
            target=target,
            function_name=function_name,
            abi_file=abi_file,
            abi_fragment=abi_fragment,
            args_json=args_json,
            value=value,
            network_name=network_name,
            nonce=nonce,
            gas_limit=gas_limit,
            gas_price_gwei=gas_price_gwei,
            max_fee_per_gas_gwei=max_fee_per_gas_gwei,
            max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
        )
        return self._simulate_prepared_transaction(preview, f"Simulation for {preview['network_name']}")

    def execute_contract_write(
        self,
        passphrase: str,
        preview: dict[str, Any] | None = None,
        from_account_name: str | None = None,
        target: str | None = None,
        function_name: str | None = None,
        abi_file: str | None = None,
        abi_fragment: str | None = None,
        args_json: str | None = None,
        value: str | None = None,
        network_name: str | None = None,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        if preview is None:
            if not from_account_name or not target or not function_name:
                raise ValidationError("From account, target, and function are required.")
            preview = self.preview_contract_write(
                from_account_name=from_account_name,
                target=target,
                function_name=function_name,
                abi_file=abi_file,
                abi_fragment=abi_fragment,
                args_json=args_json,
                value=value,
                network_name=network_name,
                nonce=nonce,
                gas_limit=gas_limit,
                gas_price_gwei=gas_price_gwei,
                max_fee_per_gas_gwei=max_fee_per_gas_gwei,
                max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
            )
        return self._execute_prepared_transaction(passphrase, preview)

    def token_allowance(
        self,
        token_target: str,
        owner: str,
        spender: str,
        network_name: str | None = None,
    ) -> dict[str, Any]:
        network = self._networks().get_network(network_name)
        token_resolution = self._resolve_lookup_target(token_target, network["name"])
        owner_resolution = self._resolve_lookup_target(owner, network["name"])
        spender_resolution = self._resolve_lookup_target(spender, network["name"])
        payload = EVMClient(network).get_token_allowance(
            token_address=token_resolution["address"],
            owner=owner_resolution["address"],
            spender=spender_resolution["address"],
        )
        payload.update(
            {
                "summary": f"Token allowance for {payload['token_address']} on {network['name']}",
                "profile": self.profile_name,
                "network": network["name"],
                "chain_id": network["chain_id"],
                "token_query": token_resolution["query"],
                "token_query_kind": token_resolution["query_kind"],
                "owner_query": owner_resolution["query"],
                "owner_query_kind": owner_resolution["query_kind"],
                "spender_query": spender_resolution["query"],
                "spender_query_kind": spender_resolution["query_kind"],
            }
        )
        return payload

    def preview_token_approve(
        self,
        from_account_name: str,
        token_target: str,
        spender: str,
        amount: str,
        network_name: str | None = None,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        account = self._resolve_account_metadata(from_account_name)
        network = self._networks().get_network(network_name)
        token_resolution = self._resolve_lookup_target(token_target, network["name"])
        spender_resolution = self._resolve_lookup_target(spender, network["name"])
        prepared = EVMClient(network).prepare_token_approve(
            from_address=account["address"],
            token_address=token_resolution["address"],
            spender_address=spender_resolution["address"],
            amount=amount,
            nonce=nonce,
            gas_limit=gas_limit,
            gas_price_gwei=gas_price_gwei,
            max_fee_per_gas_gwei=max_fee_per_gas_gwei,
            max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
        )
        details = {
            "kind": "token_approve",
            "token_query": token_resolution["query"],
            "token_query_kind": token_resolution["query_kind"],
            "spender_query": spender_resolution["query"],
            "spender_query_kind": spender_resolution["query_kind"],
            "spender_address": spender_resolution["address"],
            "amount": amount,
            "amount_raw": prepared["amount_raw"],
            "symbol": prepared["symbol"],
            "decimals": prepared["decimals"],
        }
        query_name = spender_resolution["query"] if spender_resolution["query_kind"] != "raw" else None
        payload = self._finalize_prepared_transaction(
            prepared=prepared,
            account=account,
            network=network,
            query=token_resolution["query"],
            query_kind=token_resolution["query_kind"],
            recipient_name=query_name,
            action="token_approve",
            details=details,
            policy_asset_type="erc20",
            policy_amount=amount,
            policy_token_address=token_resolution["address"],
        )
        payload["spender_query"] = spender_resolution["query"]
        payload["spender_query_kind"] = spender_resolution["query_kind"]
        payload["spender_address"] = spender_resolution["address"]
        return payload

    def simulate_token_approve(
        self,
        from_account_name: str,
        token_target: str,
        spender: str,
        amount: str,
        network_name: str | None = None,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        preview = self.preview_token_approve(
            from_account_name=from_account_name,
            token_target=token_target,
            spender=spender,
            amount=amount,
            network_name=network_name,
            nonce=nonce,
            gas_limit=gas_limit,
            gas_price_gwei=gas_price_gwei,
            max_fee_per_gas_gwei=max_fee_per_gas_gwei,
            max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
        )
        return self._simulate_prepared_transaction(preview, f"Simulation for {preview['network_name']}")

    def execute_token_approve(
        self,
        passphrase: str,
        preview: dict[str, Any] | None = None,
        from_account_name: str | None = None,
        token_target: str | None = None,
        spender: str | None = None,
        amount: str | None = None,
        network_name: str | None = None,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        if preview is None:
            if not from_account_name or not token_target or not spender or amount is None:
                raise ValidationError("From account, token, spender, and amount are required.")
            preview = self.preview_token_approve(
                from_account_name=from_account_name,
                token_target=token_target,
                spender=spender,
                amount=amount,
                network_name=network_name,
                nonce=nonce,
                gas_limit=gas_limit,
                gas_price_gwei=gas_price_gwei,
                max_fee_per_gas_gwei=max_fee_per_gas_gwei,
                max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
            )
        return self._execute_prepared_transaction(passphrase, preview)

    def lookup_address(self, target: str, network_name: str | None = None) -> dict[str, Any]:
        network = self._networks().get_network(network_name)
        resolved = self._resolve_lookup_target(target, network["name"])
        client = EVMClient(network)
        inspection = client.inspect_address(resolved["address"])
        native_balance = client.get_native_balance(inspection["address"])
        return {
            "summary": f"Lookup address for {inspection['address']} on {network['name']}",
            "profile": self.profile_name,
            "network": network["name"],
            "chain_id": network["chain_id"],
            "query": resolved["query"],
            "query_kind": resolved["query_kind"],
            "address": inspection["address"],
            "classification": inspection["classification"],
            "nonce": inspection["nonce"],
            "native_balance": {
                "symbol": native_balance["symbol"],
                "balance_wei": native_balance["balance_wei"],
                "balance": native_balance["balance"],
            },
            "code_present": inspection["code_present"],
            "code_size_bytes": inspection["code_size_bytes"],
            "detected_interfaces": inspection["detected_interfaces"],
            "proxy_hints": inspection["proxy_hints"],
        }

    def lookup_token(
        self,
        target: str,
        network_name: str | None = None,
        holder: str | None = None,
    ) -> dict[str, Any]:
        network = self._networks().get_network(network_name)
        resolved = self._resolve_lookup_target(target, network["name"])
        holder_resolution = self._resolve_lookup_target(holder, network["name"]) if holder else None
        client = EVMClient(network)
        inspection = client.inspect_token(
            resolved["address"],
            holder=holder_resolution["address"] if holder_resolution else None,
        )
        payload = {
            "summary": f"Lookup token for {inspection['address']} on {network['name']}",
            "profile": self.profile_name,
            "network": network["name"],
            "chain_id": network["chain_id"],
            "query": resolved["query"],
            "query_kind": resolved["query_kind"],
            "address": inspection["address"],
            "token_standard": inspection["token_standard"],
            "name": inspection["name"],
            "symbol": inspection["symbol"],
            "decimals": inspection["decimals"],
            "total_supply": inspection["total_supply"],
            "is_contract": inspection["is_contract"],
            "code_size_bytes": inspection["code_size_bytes"],
            "detected_interfaces": inspection["detected_interfaces"],
            "proxy_hints": inspection["proxy_hints"],
        }
        if inspection.get("metadata_uri") is not None:
            payload["metadata_uri"] = inspection["metadata_uri"]
        if holder_resolution:
            holder_payload = dict(inspection.get("holder") or {})
            holder_payload.update(
                {
                    "query": holder_resolution["query"],
                    "query_kind": holder_resolution["query_kind"],
                    "address": holder_payload.get("address") or holder_resolution["address"],
                }
            )
            payload["holder"] = holder_payload
        return payload

    def lookup_contract(self, target: str, network_name: str | None = None) -> dict[str, Any]:
        network = self._networks().get_network(network_name)
        resolved = self._resolve_lookup_target(target, network["name"])
        client = EVMClient(network)
        inspection = client.inspect_contract(resolved["address"])
        token_hints = inspection.get("token_hints") or {}
        payload = {
            "summary": f"Lookup contract for {inspection['address']} on {network['name']}",
            "profile": self.profile_name,
            "network": network["name"],
            "chain_id": network["chain_id"],
            "query": resolved["query"],
            "query_kind": resolved["query_kind"],
            "address": inspection["address"],
            "classification": inspection["classification"],
            "nonce": inspection["nonce"],
            "code_present": inspection["code_present"],
            "code_size_bytes": inspection["code_size_bytes"],
            "detected_interfaces": inspection["detected_interfaces"],
            "proxy_hints": inspection["proxy_hints"],
            "token_standard": token_hints.get("token_standard", "unknown"),
            "name": token_hints.get("name"),
            "symbol": token_hints.get("symbol"),
            "decimals": token_hints.get("decimals"),
            "total_supply": token_hints.get("total_supply"),
        }
        if token_hints.get("metadata_uri") is not None:
            payload["metadata_uri"] = token_hints["metadata_uri"]
        return payload

    def balance_snapshot(
        self,
        account_name: str | None = None,
        network_name: str | None = None,
        token_address: str | None = None,
    ) -> dict[str, Any]:
        effective_account_name = account_name or self._accounts().get_default_account_name()
        effective_network_name = network_name or load_json(self.paths.networks_file, {"default_network": None}).get(
            "default_network"
        )
        if not effective_account_name or not effective_network_name:
            return {
                "summary": "Balance snapshot unavailable",
                "status": "unconfigured",
                "profile": self.profile_name,
                "account_name": effective_account_name,
                "network_name": effective_network_name,
                "message": "Set a default account and network to enable sidebar balance snapshots.",
            }
        try:
            payload = self.balance(
                account_name=effective_account_name,
                network_name=effective_network_name,
                token_address=token_address,
            )
        except VaultError as exc:
            return {
                "summary": "Balance snapshot unavailable",
                "status": "error",
                "profile": self.profile_name,
                "account_name": effective_account_name,
                "network_name": effective_network_name,
                "message": str(exc),
            }
        payload["status"] = "ok"
        return payload

    def preview_send(
        self,
        from_account_name: str | None = None,
        network_name: str | None = None,
        recipient: str | None = None,
        amount: str | None = None,
        token_address: str | None = None,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        if not recipient:
            raise ValidationError("Recipient is required.")
        if not amount:
            raise ValidationError("Amount is required.")

        account = self._resolve_account_metadata(from_account_name)
        network = self._networks().get_network(network_name)
        recipient_entry = self._address_book().resolve(recipient, network["name"])
        client = EVMClient(network)
        prepared = (
            client.prepare_token_transfer(
                from_address=account["address"],
                token_address=token_address,
                to_address=recipient_entry["address"],
                amount=amount,
                nonce=nonce,
                gas_limit=gas_limit,
                gas_price_gwei=gas_price_gwei,
                max_fee_per_gas_gwei=max_fee_per_gas_gwei,
                max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
            )
            if token_address
            else client.prepare_native_transfer(
                from_address=account["address"],
                to_address=recipient_entry["address"],
                amount=amount,
                nonce=nonce,
                gas_limit=gas_limit,
                gas_price_gwei=gas_price_gwei,
                max_fee_per_gas_gwei=max_fee_per_gas_gwei,
                max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
            )
        )
        prepared["profile"] = self.profile_name
        prepared["account_name"] = account["name"]
        prepared["account_kind"] = account.get("account_kind", "local")
        prepared["signer_type"] = account.get("signer_type", "local")
        prepared["can_sign"] = account.get("can_sign", True)
        prepared["recipient_name"] = recipient_entry["name"]
        prepared["network_name"] = network["name"]
        prepared["requires_strong_confirmation"] = requires_strong_confirmation(self.profile_name, network)
        prepared["action"] = "send"
        policy = self._policies().evaluate_action(
            account_name=account["name"],
            network_name=network["name"],
            recipient_address=recipient_entry["address"],
            asset_type=prepared["asset_type"],
            amount=amount,
            token_address=token_address,
            protected=prepared["requires_strong_confirmation"],
        )
        if not policy["allowed"]:
            raise ValidationError("; ".join(policy["findings"]))
        prepared["policy_findings"] = policy["findings"]
        prepared["requires_simulation"] = policy["requires_simulation"]
        return prepared

    def simulate_send(
        self,
        from_account_name: str | None = None,
        network_name: str | None = None,
        recipient: str | None = None,
        amount: str | None = None,
        token_address: str | None = None,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        preview = self.preview_send(
            from_account_name=from_account_name,
            network_name=network_name,
            recipient=recipient,
            amount=amount,
            token_address=token_address,
            nonce=nonce,
            gas_limit=gas_limit,
            gas_price_gwei=gas_price_gwei,
            max_fee_per_gas_gwei=max_fee_per_gas_gwei,
            max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
        )
        network = self._networks().get_network(preview["network_name"])
        simulation = EVMClient(network).simulate_transaction(preview["tx"])
        simulation.update(
            {
                "summary": f"Simulation for {preview['network_name']}",
                "profile": self.profile_name,
                "account_name": preview["account_name"],
                "network_name": preview["network_name"],
                "to_address": preview["to_address"],
                "recipient_name": preview["recipient_name"],
                "asset_type": preview["asset_type"],
                "amount": preview["amount"],
                "token_address": preview.get("token_address"),
                "requires_simulation": preview["requires_simulation"],
            }
        )
        return simulation

    def execute_send(
        self,
        passphrase: str,
        preview: dict[str, Any] | None = None,
        from_account_name: str | None = None,
        network_name: str | None = None,
        recipient: str | None = None,
        amount: str | None = None,
        token_address: str | None = None,
        nonce: int | None = None,
        gas_limit: int | None = None,
        gas_price_gwei: str | None = None,
        max_fee_per_gas_gwei: str | None = None,
        max_priority_fee_per_gas_gwei: str | None = None,
    ) -> dict[str, Any]:
        if preview is None:
            preview = self.preview_send(
                from_account_name=from_account_name,
                network_name=network_name,
                recipient=recipient,
                amount=amount,
                token_address=token_address,
                nonce=nonce,
                gas_limit=gas_limit,
                gas_price_gwei=gas_price_gwei,
                max_fee_per_gas_gwei=max_fee_per_gas_gwei,
                max_priority_fee_per_gas_gwei=max_priority_fee_per_gas_gwei,
            )
        return self._execute_prepared_transaction(passphrase, preview)

    def monitor_show_state(self, account_name: str | None = None, network_name: str | None = None) -> dict[str, Any]:
        account = self._resolve_account_metadata(account_name)
        network = self._networks().get_network(network_name)
        state = self._monitor_state().get_state(account["name"], network["name"])
        return {
            "summary": f"Monitor state for {account['name']} on {network['name']}",
            "profile": self.profile_name,
            "account_name": account["name"],
            "address": account["address"],
            "network": network["name"],
            "chain_id": network["chain_id"],
            "state": state
            or {
                "account_name": account["name"],
                "network_name": network["name"],
                "address": account["address"],
                "last_processed_block": None,
                "last_known_nonce": None,
                "last_native_balance": None,
                "observed_tx_hashes": [],
                "settled_tx_hashes": [],
                "last_poll_at": None,
                "updated_at": None,
            },
        }

    def monitor_list_events(
        self,
        account_name: str | None = None,
        network_name: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        account = self._resolve_account_metadata(account_name)
        network = self._networks().get_network(network_name)
        rows = self._journal().monitor_entries(account["name"], network["name"], limit=limit)
        return {
            "summary": f"Found {len(rows)} monitor event(s)",
            "profile": self.profile_name,
            "account_name": account["name"],
            "address": account["address"],
            "network": network["name"],
            "events": rows,
            "count": len(rows),
        }

    def monitor_poll(self, account_name: str | None = None, network_name: str | None = None) -> dict[str, Any]:
        account = self._resolve_account_metadata(account_name)
        network = self._networks().get_network(network_name)
        client = EVMClient(network)
        state = self._monitor_state().get_state(account["name"], network["name"]) or {
            "account_name": account["name"],
            "network_name": network["name"],
            "address": account["address"],
            "last_processed_block": None,
            "last_known_nonce": None,
            "last_native_balance": None,
            "observed_tx_hashes": [],
            "settled_tx_hashes": [],
            "last_poll_at": None,
            "updated_at": None,
        }
        latest_block = client.get_latest_block_number()
        native_balance = client.get_native_balance(account["address"])
        current_nonce = client.get_transaction_count(account["address"])
        poll_time = now_iso()

        new_events: list[dict[str, Any]] = []
        new_events.extend(self._monitor_pending_receipts(account, network, client, state, poll_time))

        if state["last_processed_block"] is None:
            state["last_processed_block"] = latest_block
        elif latest_block > int(state["last_processed_block"]):
            new_events.extend(
                self._monitor_new_blocks(
                    account=account,
                    network=network,
                    client=client,
                    state=state,
                    start_block=int(state["last_processed_block"]) + 1,
                    end_block=latest_block,
                    created_at=poll_time,
                )
            )
            state["last_processed_block"] = latest_block

        previous_balance = state.get("last_native_balance")
        if previous_balance is not None and previous_balance != native_balance["balance_wei"]:
            delta = int(native_balance["balance_wei"]) - int(previous_balance)
            new_events.append(
                self._journal().record_event(
                    build_monitor_event_id(account["name"], network["name"], "native-balance", poll_time),
                    "monitor_balance_change",
                    {
                        "kind": "observation",
                        "origin": "monitor",
                        "event_type": "native_balance_changed",
                        "status": "observed",
                        "profile": self.profile_name,
                        "network": network["name"],
                        "chain_id": network["chain_id"],
                        "account_name": account["name"],
                        "address": account["address"],
                        "asset_type": "native",
                        "symbol": network["symbol"],
                        "amount": format_units(abs(delta), 18),
                        "amount_wei": str(abs(delta)),
                        "created_at": poll_time,
                        "details": {
                            "direction": "increase" if delta >= 0 else "decrease",
                            "previous_balance_wei": previous_balance,
                            "current_balance_wei": native_balance["balance_wei"],
                            "delta_wei": str(delta),
                            "previous_balance": format_units(int(previous_balance), 18),
                            "current_balance": native_balance["balance"],
                            "delta": format_units(abs(delta), 18),
                        },
                    },
                )
            )

        state["last_known_nonce"] = current_nonce
        state["last_native_balance"] = native_balance["balance_wei"]
        state["last_poll_at"] = poll_time
        state["updated_at"] = poll_time
        saved_state = self._monitor_state().save_state(account["name"], network["name"], state)
        return {
            "summary": f"Monitor poll for {account['name']} on {network['name']}",
            "profile": self.profile_name,
            "account_name": account["name"],
            "address": account["address"],
            "network": network["name"],
            "chain_id": network["chain_id"],
            "once": True,
            "latest_block": latest_block,
            "current_nonce": current_nonce,
            "native_balance": native_balance,
            "new_events": new_events,
            "new_event_count": len(new_events),
            "state": saved_state,
        }

    def monitor_watch(
        self,
        account_name: str | None = None,
        network_name: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        while True:
            yield self.monitor_poll(account_name=account_name, network_name=network_name)

    def safety_status(self) -> dict[str, Any]:
        prod_paths = resolve_paths(home=self.home_arg, profile="prod")
        dev_paths = resolve_paths(home=self.home_arg, profile="dev")
        prod_accounts = KeystoreManager(prod_paths).list_accounts()
        prod_networks = NetworkManager(prod_paths).list_networks()
        dev_accounts = KeystoreManager(dev_paths).list_accounts()
        dev_networks = NetworkManager(dev_paths).list_networks()

        findings = []
        prod_default_account = prod_accounts.get("default_account")
        prod_default_network = prod_networks.get("default_network")
        if prod_default_account and is_dev_like_account(prod_default_account):
            findings.append(f"Prod default account `{prod_default_account}` looks like a development account.")
        if prod_default_network and is_dev_like_network(prod_default_network):
            findings.append(f"Prod default network `{prod_default_network}` looks like a development network.")

        prod_names = {item["name"] for item in prod_accounts["accounts"]}
        prod_network_names = {item["name"] for item in prod_networks["networks"]}
        dev_names = {item["name"] for item in dev_accounts["accounts"]}
        dev_network_names = {item["name"] for item in dev_networks["networks"]}

        if "local-dev" in prod_names and "local-dev" not in dev_names:
            findings.append("Dev account `local-dev` exists only in prod.")
        if "local" in prod_network_names and "local" not in dev_network_names:
            findings.append("Dev network `local` exists only in prod.")
        if path_is_within_git_worktree(self.paths.root_home):
            findings.append(
                f"Vault home `{self.paths.root_home}` is inside a git worktree. Move it outside the repo before publishing or committing."
            )
        if not findings:
            findings.append("No immediate safety issues detected.")

        return {
            "summary": "Safety status",
            "active_profile": self.profile_name,
            "storage_root": str(self.paths.root_home),
            "prod_default_account": prod_default_account,
            "prod_default_network": prod_default_network,
            "dev_default_account": dev_accounts.get("default_account"),
            "dev_default_network": dev_networks.get("default_network"),
            "findings": findings,
        }

    def separate_dev(
        self,
        prod_account: str,
        prod_network: str,
        dev_account: str,
        dev_network: str,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        prod_paths = resolve_paths(home=self.home_arg, profile="prod")
        dev_paths = resolve_paths(home=self.home_arg, profile="dev")
        actions: list[dict[str, Any]] = []

        actions.append({"action": "set_prod_default_account", "value": prod_account})
        actions.append({"action": "set_prod_default_network", "value": prod_network})
        actions.append({"action": "copy_account_to_dev", "value": dev_account})
        actions.append({"action": "copy_network_to_dev", "value": dev_network})
        actions.append({"action": "set_dev_default_account", "value": dev_account})
        actions.append({"action": "set_dev_default_network", "value": dev_network})

        if dry_run:
            return {
                "summary": "Planned dev separation",
                "actions": actions,
                "profile": self.profile_name,
            }

        prod_accounts = KeystoreManager(prod_paths)
        prod_networks = NetworkManager(prod_paths)
        dev_accounts = KeystoreManager(dev_paths)
        dev_networks = NetworkManager(dev_paths)

        prod_accounts.set_default_account(prod_account)
        prod_networks.set_default_network(prod_network)

        copied_account = copy_account_file(prod_paths, dev_paths, dev_account, overwrite=overwrite)
        copied_network = copy_network_record(prod_paths, dev_paths, dev_network, overwrite=overwrite)

        dev_accounts.set_default_account(dev_account)
        dev_networks.set_default_network(dev_network)

        return {
            "summary": "Separated development defaults from prod",
            "profile": self.profile_name,
            "prod_default_account": prod_account,
            "prod_default_network": prod_network,
            "dev_default_account": dev_account,
            "dev_default_network": dev_network,
            "copied_account": copied_account,
            "copied_network": copied_network,
        }

    def _accounts(self) -> KeystoreManager:
        return KeystoreManager(self.paths)

    def _networks(self) -> NetworkManager:
        return NetworkManager(self.paths)

    def _address_book(self) -> AddressBookManager:
        return AddressBookManager(self.paths)

    def _journal(self) -> JournalManager:
        return JournalManager(self.paths)

    def _monitor_state(self) -> MonitorStateManager:
        return MonitorStateManager(self.paths)

    def _policies(self) -> PolicyManager:
        return PolicyManager(self.paths)

    def _profile_has_data(self, paths: Any) -> bool:
        return any(
            path.exists()
            for path in (
                paths.accounts_dir,
                paths.config_file,
                paths.networks_file,
                paths.address_book_file,
                paths.journal_file,
                paths.monitor_state_file,
                paths.policy_file,
            )
        )

    def _resolve_account_metadata(self, account_name: str | None) -> dict[str, Any]:
        accounts = self._accounts()
        effective_name = account_name or accounts.get_default_account_name()
        if not effective_name:
            raise ValidationError("No account selected. Create/import an account or set a default account first.")
        return accounts.get_account_metadata(effective_name)

    def _resolve_lookup_target(self, target: str | None, network_name: str | None) -> dict[str, Any]:
        candidate = (target or "").strip()
        if not candidate:
            raise ValidationError("Lookup target cannot be empty.")
        if candidate.startswith("0x"):
            return {
                "query": candidate,
                "query_kind": "raw",
                "address": normalize_address(candidate),
            }

        normalized_name: str
        accounts = self._accounts()
        try:
            normalized_name = candidate.strip().lower()
            if accounts.has_account(normalized_name):
                metadata = accounts.get_account_metadata(normalized_name)
                return {
                    "query": candidate,
                    "query_kind": "account",
                    "address": metadata["address"],
                }
        except ValidationError:
            pass

        try:
            entry = self._address_book().resolve(candidate, network_name)
        except NotFoundError as exc:
            raise NotFoundError(
                f"Lookup target `{candidate}` was not found as a raw address, stored account, or address book label."
            ) from exc
        return {
            "query": candidate,
            "query_kind": "address_book",
            "address": entry["address"],
        }

    def _resolve_signer(self, account_name: str | None):
        metadata = self._resolve_account_metadata(account_name)
        return resolve_signer(self.paths, metadata)

    def _load_abi(self, abi_file: str | None = None, abi_fragment: str | None = None) -> tuple[list[dict[str, Any]], str, str]:
        if bool(abi_file) == bool(abi_fragment):
            raise ValidationError("Provide exactly one of `--abi-file` or `--abi-fragment`.")
        if abi_file:
            try:
                with open(abi_file, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except OSError as exc:
                raise ValidationError(f"Could not read ABI file `{abi_file}`.") from exc
            except json.JSONDecodeError as exc:
                raise ValidationError(f"ABI file `{abi_file}` must contain valid JSON.") from exc
            abi = payload.get("abi") if isinstance(payload, dict) and "abi" in payload else payload
            if not isinstance(abi, list):
                raise ValidationError("ABI files must contain a JSON ABI array or an object with an `abi` field.")
            return abi, "file", abi_file
        try:
            fragment = json.loads(abi_fragment or "")
        except json.JSONDecodeError as exc:
            raise ValidationError("ABI fragment must be valid JSON.") from exc
        if isinstance(fragment, dict):
            abi = [fragment]
        elif isinstance(fragment, list):
            abi = fragment
        else:
            raise ValidationError("ABI fragment must be a JSON object or array.")
        return abi, "fragment", "inline"

    def _parse_args_json(self, args_json: str | None) -> list[Any]:
        if not args_json:
            return []
        try:
            payload = json.loads(args_json)
        except json.JSONDecodeError as exc:
            raise ValidationError("Arguments must be a valid JSON array.") from exc
        if not isinstance(payload, list):
            raise ValidationError("Arguments must be provided as a JSON array.")
        return payload

    def _finalize_prepared_transaction(
        self,
        prepared: dict[str, Any],
        account: dict[str, Any],
        network: dict[str, Any],
        query: str,
        query_kind: str,
        recipient_name: str | None,
        action: str,
        details: dict[str, Any] | None,
        policy_asset_type: str,
        policy_amount: str,
        policy_token_address: str | None,
    ) -> dict[str, Any]:
        prepared["profile"] = self.profile_name
        prepared["account_name"] = account["name"]
        prepared["account_kind"] = account.get("account_kind", "local")
        prepared["signer_type"] = account.get("signer_type", "local")
        prepared["can_sign"] = account.get("can_sign", True)
        prepared["network_name"] = network["name"]
        prepared["query"] = query
        prepared["query_kind"] = query_kind
        prepared["recipient_name"] = recipient_name
        prepared["action"] = action
        prepared["details"] = details
        prepared["requires_strong_confirmation"] = requires_strong_confirmation(self.profile_name, network)
        policy = self._policies().evaluate_action(
            account_name=account["name"],
            network_name=network["name"],
            recipient_address=prepared["to_address"],
            asset_type=policy_asset_type,
            amount=policy_amount,
            token_address=policy_token_address,
            protected=prepared["requires_strong_confirmation"],
        )
        if not policy["allowed"]:
            raise ValidationError("; ".join(policy["findings"]))
        prepared["policy_findings"] = policy["findings"]
        prepared["requires_simulation"] = policy["requires_simulation"]
        return prepared

    def _simulate_prepared_transaction(self, preview: dict[str, Any], summary: str) -> dict[str, Any]:
        network = self._networks().get_network(preview["network_name"])
        simulation = EVMClient(network).simulate_transaction(preview["tx"])
        simulation.update(
            {
                "summary": summary,
                "profile": self.profile_name,
                "account_name": preview["account_name"],
                "network_name": preview["network_name"],
                "to_address": preview["to_address"],
                "recipient_name": preview.get("recipient_name"),
                "asset_type": preview["asset_type"],
                "token_address": preview.get("token_address"),
                "contract_function": preview.get("contract_function"),
                "args": preview.get("args"),
                "value": preview.get("value"),
                "amount": preview.get("amount"),
                "requires_simulation": preview["requires_simulation"],
            }
        )
        return simulation

    def _execute_prepared_transaction(self, passphrase: str, preview: dict[str, Any]) -> dict[str, Any]:
        if preview.get("profile") != self.profile_name:
            raise ValidationError("Prepared transaction does not belong to the active profile.")
        account_name = preview["account_name"]
        signer = resolve_signer(
            self.paths,
            {
                "name": account_name,
                "address": preview["from_address"],
                "account_kind": preview.get("account_kind", "local"),
                "signer_type": preview.get("signer_type", "local"),
                "can_sign": preview.get("can_sign", True),
            },
        )
        network = self._networks().get_network(preview["network_name"])
        simulation = None
        if preview.get("requires_simulation"):
            simulation = EVMClient(network).simulate_transaction(preview["tx"])
            if simulation["status"] != "success":
                raise ValidationError("Protected transaction simulation failed. Broadcast cancelled.")
        payload = signer.send_prepared(passphrase, preview, network)
        payload["profile"] = self.profile_name
        payload["account_name"] = account_name
        payload["recipient_name"] = preview.get("recipient_name")
        payload["requires_strong_confirmation"] = preview["requires_strong_confirmation"]
        payload["submitted_at"] = now_iso()
        payload["action"] = preview.get("action", payload.get("action", "send"))
        payload["details"] = preview.get("details")
        self._journal().record_submitted_transaction(payload, simulation=simulation)
        return payload

    def _monitor_pending_receipts(
        self,
        account: dict[str, Any],
        network: dict[str, Any],
        client: EVMClient,
        state: dict[str, Any],
        created_at: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        settled = set(state.get("settled_tx_hashes") or [])
        for entry in self._journal().transaction_entries():
            tx_hash = entry.get("tx_hash")
            if not tx_hash:
                continue
            if entry.get("account_name") != account["name"] or entry.get("network") != network["name"]:
                continue
            if entry.get("receipt") or tx_hash in settled:
                continue
            receipt = client.get_transaction_receipt_or_none(tx_hash)
            if not receipt:
                continue
            self._journal().attach_receipt(tx_hash, receipt)
            events.append(
                self._journal().record_event(
                    build_monitor_event_id(account["name"], network["name"], f"receipt-{tx_hash[-8:]}", created_at),
                    "monitor_receipt",
                    {
                        "kind": "observation",
                        "origin": "monitor",
                        "event_type": "transaction_confirmed" if receipt["status"] == 1 else "transaction_failed",
                        "status": "confirmed" if receipt["status"] == 1 else "failed",
                        "profile": self.profile_name,
                        "network": network["name"],
                        "chain_id": network["chain_id"],
                        "account_name": account["name"],
                        "address": account["address"],
                        "tx_hash": tx_hash,
                        "created_at": created_at,
                        "details": {
                            "source": "journal",
                            "block_number": receipt.get("block_number"),
                            "gas_used": receipt.get("gas_used"),
                        },
                    },
                )
            )
            settled.add(tx_hash)
        state["settled_tx_hashes"] = trim_hash_cache(settled)
        return events

    def _monitor_new_blocks(
        self,
        account: dict[str, Any],
        network: dict[str, Any],
        client: EVMClient,
        state: dict[str, Any],
        start_block: int,
        end_block: int,
        created_at: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        observed = set(state.get("observed_tx_hashes") or [])
        settled = set(state.get("settled_tx_hashes") or [])
        for tx in client.get_relevant_transactions(account["address"], start_block, end_block):
            tx_hash = tx["transaction_hash"]
            direction = "outgoing" if tx["from_address"].lower() == account["address"].lower() else "incoming"
            if tx_hash not in observed:
                events.append(
                    self._journal().record_event(
                        build_monitor_event_id(account["name"], network["name"], f"{direction}-{tx_hash[-8:]}", created_at),
                        "monitor_transaction_observed",
                        {
                            "kind": "observation",
                            "origin": "monitor",
                            "event_type": f"{direction}_transaction_observed",
                            "status": "observed",
                            "profile": self.profile_name,
                            "network": network["name"],
                            "chain_id": network["chain_id"],
                            "account_name": account["name"],
                            "address": account["address"],
                            "from_address": tx["from_address"],
                            "to_address": tx["to_address"],
                            "asset_type": "native",
                            "symbol": network["symbol"],
                            "amount": format_units(int(tx["value_wei"]), 18),
                            "amount_wei": tx["value_wei"],
                            "nonce": tx["nonce"],
                            "tx_hash": tx_hash,
                            "created_at": created_at,
                            "details": {
                                "block_number": tx["block_number"],
                                "direction": direction,
                            },
                        },
                    )
                )
                observed.add(tx_hash)

            receipt = client.get_transaction_receipt_or_none(tx_hash)
            if receipt and tx_hash not in settled:
                try:
                    self._journal().attach_receipt(tx_hash, receipt)
                except NotFoundError:
                    pass
                events.append(
                    self._journal().record_event(
                        build_monitor_event_id(account["name"], network["name"], f"confirmed-{tx_hash[-8:]}", created_at),
                        "monitor_receipt",
                        {
                            "kind": "observation",
                            "origin": "monitor",
                            "event_type": "transaction_confirmed" if receipt["status"] == 1 else "transaction_failed",
                            "status": "confirmed" if receipt["status"] == 1 else "failed",
                            "profile": self.profile_name,
                            "network": network["name"],
                            "chain_id": network["chain_id"],
                            "account_name": account["name"],
                            "address": account["address"],
                            "tx_hash": tx_hash,
                            "created_at": created_at,
                            "details": {
                                "source": "block-scan",
                                "block_number": receipt.get("block_number"),
                                "gas_used": receipt.get("gas_used"),
                            },
                        },
                    )
                )
                settled.add(tx_hash)
        state["observed_tx_hashes"] = trim_hash_cache(observed)
        state["settled_tx_hashes"] = trim_hash_cache(settled)
        return events


def build_monitor_event_id(account_name: str, network_name: str, label: str, created_at: str) -> str:
    return f"monitor:{account_name}:{network_name}:{label}:{created_at}"


def trim_hash_cache(values: set[str]) -> list[str]:
    return sorted(values)[-MAX_MONITOR_CACHE:]


def requires_strong_confirmation(profile_name: str, network: dict[str, Any]) -> bool:
    return profile_name == "prod" or int(network["chain_id"]) in MAINNET_CHAIN_IDS


def is_dev_like_account(name: str) -> bool:
    return name.startswith("local") or name.startswith("dev")


def is_dev_like_network(name: str) -> bool:
    return name == "local" or name.startswith("dev")
