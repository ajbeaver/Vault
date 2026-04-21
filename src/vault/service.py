from __future__ import annotations

from typing import Any

from vault.address_book import AddressBookManager
from vault.config import (
    DEFAULT_PROFILES,
    VaultError,
    ValidationError,
    load_json,
    resolve_paths,
    resolve_root_home,
    save_json,
    set_active_profile_name,
)
from vault.erc4337 import ERC4337Client
from vault.evm import EVMClient
from vault.journal import JournalManager
from vault.keystore import KeystoreManager, copy_account_file, now_iso
from vault.networks import NetworkManager, copy_network_record
from vault.policy import PolicyManager
from vault.safe import SAFE_TRANSACTION_SENTINEL, SafeClient
from vault.signers import resolve_signer
from vault.smart_accounts import SmartAccountManager
from vault.themes import DEFAULT_THEME_NAME, normalize_theme_name, theme_rows


MAINNET_CHAIN_IDS = {1, 10, 137, 8453, 42161}


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
        smart_payload = self._smart_accounts().list_accounts()
        config = load_json(self.paths.config_file, {})
        default_account_name = accounts_payload.get("default_account")
        default_network_name = networks_payload.get("default_network")
        default_smart_name = smart_payload.get("default_smart_account")
        default_account = next(
            (item for item in accounts_payload["accounts"] if item["name"] == default_account_name),
            None,
        )
        default_network = next(
            (item for item in networks_payload["networks"] if item["name"] == default_network_name),
            None,
        )
        default_smart_account = next(
            (item for item in smart_payload["accounts"] if item["name"] == default_smart_name),
            None,
        )
        return {
            "summary": f"Context for {self.profile_name}",
            "profile": self.profile_name,
            "is_protected_profile": self.profile_name == "prod",
            "default_account": default_account,
            "default_network": default_network,
            "default_smart_account": default_smart_account,
            "account_count": accounts_payload["count"],
            "network_count": networks_payload["count"],
            "smart_account_count": smart_payload["count"],
            "theme": normalize_theme_name(config.get("theme", DEFAULT_THEME_NAME)),
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
        normalized = normalize_theme_name(name)
        config["theme"] = normalized
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

    def list_smart_accounts(self) -> dict[str, Any]:
        payload = self._smart_accounts().list_accounts()
        payload["profile"] = self.profile_name
        return payload

    def show_smart_account(self, name: str | None = None) -> dict[str, Any]:
        payload = self._smart_accounts().get_account(name)
        payload["summary"] = f"Smart account {payload['name']}"
        payload["profile"] = self.profile_name
        return payload

    def use_smart_account(self, name: str) -> dict[str, Any]:
        payload = self._smart_accounts().set_default_account(name)
        payload["profile"] = self.profile_name
        return payload

    def register_safe_account(
        self,
        name: str,
        address: str,
        network_name: str,
        service_url: str | None = None,
        entrypoint: str | None = None,
        set_default: bool = False,
    ) -> dict[str, Any]:
        network = self._networks().get_network(network_name)
        info = SafeClient(network, service_url=service_url).get_safe_info(address)
        payload = self._smart_accounts().register_safe(
            name=name,
            address=info["address"],
            network=network["name"],
            owners=info["owners"],
            threshold=info["threshold"],
            service_url=service_url,
            entrypoint=entrypoint,
            set_default=set_default,
        )
        payload["profile"] = self.profile_name
        payload["nonce"] = info["nonce"]
        return payload

    def create_safe_account(
        self,
        signer_account: str,
        passphrase: str,
        network_name: str,
        singleton: str,
        factory: str,
        fallback_handler: str,
        owners: list[str],
        threshold: int,
        salt_nonce: int,
    ) -> dict[str, Any]:
        signer = self._resolve_account_metadata(signer_account)
        network = self._networks().get_network(network_name)
        payload = SafeClient(network).create_safe(
            signer_paths=self.paths,
            signer_metadata=signer,
            passphrase=passphrase,
            singleton=singleton,
            factory=factory,
            fallback_handler=fallback_handler,
            owners=owners,
            threshold=threshold,
            salt_nonce=salt_nonce,
        )
        payload["profile"] = self.profile_name
        self._journal().record_event(
            payload["transaction_hash"],
            "safe_create",
            {
                "status": "submitted",
                "profile": self.profile_name,
                "network": network["name"],
                "smart_account": None,
                "created_at": now_iso(),
                "payload": payload,
            },
        )
        return payload

    def sync_safe_account(self, name: str | None = None) -> dict[str, Any]:
        config = self._require_safe_account(name)
        network = self._networks().get_network(config["network"])
        info = SafeClient(network, service_url=config.get("service_url")).get_safe_info(config["address"])
        payload = self._smart_accounts().update_account(
            config["name"],
            {
                "owners": info["owners"],
                "threshold": info["threshold"],
            },
        )
        payload["profile"] = self.profile_name
        payload["nonce"] = info["nonce"]
        return payload

    def register_erc4337_account(
        self,
        name: str,
        sender: str,
        network_name: str,
        owner_account: str,
        entrypoint: str,
        version: str = "0.6",
        factory: str | None = None,
        factory_data: str | None = None,
        bundler_url: str | None = None,
        paymaster_url: str | None = None,
        set_default: bool = False,
    ) -> dict[str, Any]:
        network = self._networks().get_network(network_name)
        self._resolve_account_metadata(owner_account)
        payload = self._smart_accounts().register_erc4337(
            name=name,
            sender=sender,
            network=network["name"],
            owner_account=owner_account,
            entrypoint=entrypoint,
            version=version,
            factory=factory,
            factory_data=factory_data,
            bundler_url=bundler_url,
            paymaster_url=paymaster_url,
            set_default=set_default,
        )
        payload["profile"] = self.profile_name
        return payload

    def remove_smart_account(self, name: str) -> dict[str, Any]:
        payload = self._smart_accounts().remove_account(name)
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

    def show_journal_entry(self, tx_hash: str) -> dict[str, Any]:
        payload = self._journal().get_entry(tx_hash)
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

    def list_safe_pending_transactions(self, name: str | None = None) -> dict[str, Any]:
        config = self._require_safe_account(name)
        network = self._networks().get_network(config["network"])
        payload = SafeClient(network, service_url=config.get("service_url")).list_pending_transactions(config["address"])
        payload["profile"] = self.profile_name
        payload["smart_account"] = config["name"]
        return payload

    def show_safe_pending_transaction(self, safe_tx_hash: str, name: str | None = None) -> dict[str, Any]:
        config = self._require_safe_account(name)
        network = self._networks().get_network(config["network"])
        payload = SafeClient(network, service_url=config.get("service_url")).get_pending_transaction(safe_tx_hash)
        payload["profile"] = self.profile_name
        payload["smart_account"] = config["name"]
        return payload

    def propose_safe_transaction(
        self,
        name: str | None,
        signer_account: str,
        passphrase: str,
        to: str,
        value: str = "0",
        data: str = "0x",
        operation: int = 0,
        nonce: int | None = None,
        origin: str | None = None,
    ) -> dict[str, Any]:
        config = self._require_safe_account(name)
        signer = self._resolve_account_metadata(signer_account)
        self._ensure_safe_owner(config, signer["name"])
        network = self._networks().get_network(config["network"])
        self._enforce_smart_policy(
            account_name=signer["name"],
            network=network,
            recipient=to,
            amount=value,
            token_address=None,
        )
        payload = SafeClient(network, service_url=config.get("service_url")).propose_transaction(
            safe_config=config,
            signer_paths=self.paths,
            proposer_metadata=signer,
            passphrase=passphrase,
            to=to,
            value_wei=int(value),
            data=data,
            operation=operation,
            nonce=nonce,
            origin=origin,
        )
        payload["profile"] = self.profile_name
        payload["smart_account"] = config["name"]
        self._journal().record_event(
            payload["safe_tx_hash"],
            "safe_proposal",
            {
                "status": "proposed",
                "profile": self.profile_name,
                "network": network["name"],
                "smart_account": config["name"],
                "created_at": now_iso(),
                "payload": payload,
            },
        )
        return payload

    def propose_safe_add_owner(
        self,
        name: str | None,
        signer_account: str,
        passphrase: str,
        owner_address: str,
        threshold: int | None = None,
        nonce: int | None = None,
    ) -> dict[str, Any]:
        config = self._require_safe_account(name)
        network = self._networks().get_network(config["network"])
        safe_client = SafeClient(network, service_url=config.get("service_url"))
        data = safe_client.encode_add_owner(owner_address, threshold or config["threshold"])
        return self.propose_safe_transaction(
            name=config["name"],
            signer_account=signer_account,
            passphrase=passphrase,
            to=config["address"],
            value="0",
            data=data,
            operation=0,
            nonce=nonce,
            origin="vault:add-owner",
        )

    def propose_safe_remove_owner(
        self,
        name: str | None,
        signer_account: str,
        passphrase: str,
        prev_owner: str,
        owner_address: str,
        threshold: int,
        nonce: int | None = None,
    ) -> dict[str, Any]:
        config = self._require_safe_account(name)
        network = self._networks().get_network(config["network"])
        safe_client = SafeClient(network, service_url=config.get("service_url"))
        data = safe_client.encode_remove_owner(prev_owner, owner_address, threshold)
        return self.propose_safe_transaction(
            name=config["name"],
            signer_account=signer_account,
            passphrase=passphrase,
            to=config["address"],
            value="0",
            data=data,
            operation=0,
            nonce=nonce,
            origin="vault:remove-owner",
        )

    def propose_safe_change_threshold(
        self,
        name: str | None,
        signer_account: str,
        passphrase: str,
        threshold: int,
        nonce: int | None = None,
    ) -> dict[str, Any]:
        config = self._require_safe_account(name)
        network = self._networks().get_network(config["network"])
        safe_client = SafeClient(network, service_url=config.get("service_url"))
        data = safe_client.encode_change_threshold(threshold)
        return self.propose_safe_transaction(
            name=config["name"],
            signer_account=signer_account,
            passphrase=passphrase,
            to=config["address"],
            value="0",
            data=data,
            operation=0,
            nonce=nonce,
            origin="vault:change-threshold",
        )

    def confirm_safe_transaction(
        self,
        name: str | None,
        signer_account: str,
        passphrase: str,
        safe_tx_hash: str,
    ) -> dict[str, Any]:
        config = self._require_safe_account(name)
        signer = self._resolve_account_metadata(signer_account)
        self._ensure_safe_owner(config, signer["name"])
        network = self._networks().get_network(config["network"])
        payload = SafeClient(network, service_url=config.get("service_url")).confirm_transaction(
            signer_paths=self.paths,
            signer_metadata=signer,
            passphrase=passphrase,
            safe_tx_hash=safe_tx_hash,
        )
        payload["profile"] = self.profile_name
        payload["smart_account"] = config["name"]
        self._journal().record_event(
            safe_tx_hash,
            "safe_confirmation",
            {
                "status": "confirmed",
                "profile": self.profile_name,
                "network": network["name"],
                "smart_account": config["name"],
                "created_at": now_iso(),
                "payload": payload,
            },
        )
        return payload

    def execute_safe_transaction(
        self,
        name: str | None,
        signer_account: str,
        passphrase: str,
        safe_tx_hash: str,
    ) -> dict[str, Any]:
        config = self._require_safe_account(name)
        signer = self._resolve_account_metadata(signer_account)
        self._ensure_safe_owner(config, signer["name"])
        network = self._networks().get_network(config["network"])
        pending = SafeClient(network, service_url=config.get("service_url")).get_pending_transaction(safe_tx_hash)
        self._enforce_smart_policy(
            account_name=signer["name"],
            network=network,
            recipient=pending["to"],
            amount=str(int(pending["value"])),
            token_address=None,
        )
        payload = SafeClient(network, service_url=config.get("service_url")).execute_transaction(
            safe_config=config,
            signer_paths=self.paths,
            signer_metadata=signer,
            passphrase=passphrase,
            safe_tx_hash=safe_tx_hash,
        )
        payload["profile"] = self.profile_name
        payload["smart_account"] = config["name"]
        self._journal().record_event(
            safe_tx_hash,
            "safe_execution",
            {
                "status": "submitted",
                "profile": self.profile_name,
                "network": network["name"],
                "smart_account": config["name"],
                "created_at": now_iso(),
                "payload": payload,
            },
        )
        return payload

    def prepare_user_operation(
        self,
        name: str | None,
        to: str,
        value: str = "0",
        data: str = "0x",
        nonce: str | None = None,
        signature: str | None = None,
    ) -> dict[str, Any]:
        config = self._require_erc4337_account(name)
        network = self._networks().get_network(config["network"])
        payload = ERC4337Client(network, config, self.paths).prepare_user_operation(
            to=to,
            data=data,
            value_wei=int(value),
            nonce=nonce,
            signature=signature,
        )
        payload["profile"] = self.profile_name
        return payload

    def simulate_user_operation(
        self,
        name: str | None,
        user_operation: dict[str, Any],
    ) -> dict[str, Any]:
        config = self._require_erc4337_account(name)
        network = self._networks().get_network(config["network"])
        payload = ERC4337Client(network, config, self.paths).simulate_user_operation(user_operation)
        payload["profile"] = self.profile_name
        return payload

    def sign_user_operation(
        self,
        name: str | None,
        passphrase: str,
        user_operation: dict[str, Any],
    ) -> dict[str, Any]:
        config = self._require_erc4337_account(name)
        network = self._networks().get_network(config["network"])
        payload = ERC4337Client(network, config, self.paths).sign_user_operation(user_operation, passphrase)
        payload["profile"] = self.profile_name
        return payload

    def submit_user_operation(
        self,
        name: str | None,
        user_operation: dict[str, Any],
    ) -> dict[str, Any]:
        config = self._require_erc4337_account(name)
        network = self._networks().get_network(config["network"])
        if not user_operation.get("signature") or user_operation["signature"] == "0x":
            raise ValidationError("User operation must be signed before submission.")
        self._enforce_smart_policy(
            account_name=config["owner_account"],
            network=network,
            recipient=config["address"],
            amount="0",
            token_address=None,
        )
        simulation = ERC4337Client(network, config, self.paths).simulate_user_operation(user_operation)
        payload = ERC4337Client(network, config, self.paths).submit_user_operation(user_operation)
        payload["profile"] = self.profile_name
        self._journal().record_event(
            payload["user_operation_hash"],
            "erc4337_submission",
            {
                "status": "submitted",
                "profile": self.profile_name,
                "network": network["name"],
                "smart_account": config["name"],
                "created_at": now_iso(),
                "simulation": simulation,
                "payload": payload,
            },
        )
        return payload

    def user_operation_status(self, name: str | None, user_operation_hash: str) -> dict[str, Any]:
        config = self._require_erc4337_account(name)
        network = self._networks().get_network(config["network"])
        payload = ERC4337Client(network, config, self.paths).get_user_operation_status(user_operation_hash)
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

    def balance_snapshot(
        self,
        account_name: str | None = None,
        network_name: str | None = None,
        token_address: str | None = None,
    ) -> dict[str, Any]:
        effective_account_name = account_name
        effective_network_name = network_name
        if not effective_account_name:
            effective_account_name = self._accounts().get_default_account_name()
        if not effective_network_name:
            effective_network_name = load_json(self.paths.networks_file, {"default_network": None}).get("default_network")
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
        payload["recipient_name"] = preview["recipient_name"]
        payload["requires_strong_confirmation"] = preview["requires_strong_confirmation"]
        payload["submitted_at"] = now_iso()
        self._journal().record_submitted_transaction(payload, simulation=simulation)
        return payload

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
        if not findings:
            findings.append("No immediate safety issues detected.")

        return {
            "summary": "Safety status",
            "active_profile": self.profile_name,
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

    def _policies(self) -> PolicyManager:
        return PolicyManager(self.paths)

    def _smart_accounts(self) -> SmartAccountManager:
        return SmartAccountManager(self.paths)

    def _profile_has_data(self, paths: Any) -> bool:
        return any(
            path.exists()
            for path in (
                paths.accounts_dir,
                paths.config_file,
                paths.networks_file,
                paths.address_book_file,
                paths.journal_file,
                paths.policy_file,
                paths.smart_accounts_file,
            )
        )

    def _resolve_account_metadata(self, account_name: str | None) -> dict[str, Any]:
        accounts = self._accounts()
        effective_name = account_name or accounts.get_default_account_name()
        if not effective_name:
            raise ValidationError("No account selected. Create/import an account or set a default account first.")
        return accounts.get_account_metadata(effective_name)

    def _resolve_signer(self, account_name: str | None):
        metadata = self._resolve_account_metadata(account_name)
        return resolve_signer(self.paths, metadata)

    def _require_safe_account(self, name: str | None) -> dict[str, Any]:
        account = self._smart_accounts().get_account(name)
        if account["type"] != "safe":
            raise ValidationError(f"Smart account `{account['name']}` is not a Safe account.")
        return account

    def _require_erc4337_account(self, name: str | None) -> dict[str, Any]:
        account = self._smart_accounts().get_account(name)
        if account["type"] != "erc4337":
            raise ValidationError(f"Smart account `{account['name']}` is not an ERC-4337 account.")
        return account

    def _ensure_safe_owner(self, safe_config: dict[str, Any], owner_name: str) -> None:
        owner_metadata = self._resolve_account_metadata(owner_name)
        owner_address = owner_metadata["address"].lower()
        configured_owners = {str(owner).lower() for owner in safe_config["owners"]}
        if owner_address not in configured_owners:
            raise ValidationError(
                f"Account `{owner_name}` ({owner_metadata['address']}) is not configured as a Safe owner for `{safe_config['name']}`."
            )

    def _enforce_smart_policy(
        self,
        account_name: str,
        network: dict[str, Any],
        recipient: str,
        amount: str,
        token_address: str | None,
    ) -> dict[str, Any]:
        evaluation = self._policies().evaluate_action(
            account_name=account_name,
            network_name=network["name"],
            recipient_address=recipient,
            asset_type="erc20" if token_address else "native",
            amount=amount,
            token_address=token_address,
            protected=requires_strong_confirmation(self.profile_name, network),
        )
        if not evaluation["allowed"]:
            raise ValidationError("; ".join(evaluation["findings"]))
        return evaluation


def requires_strong_confirmation(profile_name: str, network: dict[str, Any]) -> bool:
    return profile_name == "prod" or int(network["chain_id"]) in MAINNET_CHAIN_IDS


def is_dev_like_account(name: str) -> bool:
    return name.startswith("local") or name.startswith("dev")


def is_dev_like_network(name: str) -> bool:
    return name == "local" or name.startswith("dev")
