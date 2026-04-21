from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from vault.config import ValidationError, VaultError
from vault.output import emit
from vault.service import VaultService


def build_parser() -> argparse.ArgumentParser:
    def add_fee_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--nonce", type=int)
        parser.add_argument("--gas-limit", type=int)
        parser.add_argument("--gas-price")
        parser.add_argument("--max-fee-per-gas")
        parser.add_argument("--max-priority-fee-per-gas")

    def add_abi_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--abi-file")
        parser.add_argument("--abi-fragment")

    parser = argparse.ArgumentParser(prog="vault", description="Operate a local-first EVM wallet from the terminal.")
    parser.add_argument("--home", help="Override the vault data directory.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    profile = subparsers.add_parser("profile", help="Manage isolated wallet profiles.")
    profile_subparsers = profile.add_subparsers(dest="profile_command", required=True)
    profile_subparsers.add_parser("list", help="List profiles.")
    profile_subparsers.add_parser("show", help="Show the active profile.")
    profile_use = profile_subparsers.add_parser("use", help="Switch the active profile.")
    profile_use.add_argument("--name", required=True, choices=["dev", "test", "prod"])

    account = subparsers.add_parser("account", help="Manage local accounts.")
    account_subparsers = account.add_subparsers(dest="account_command", required=True)
    account_create = account_subparsers.add_parser("create", help="Create a new account.")
    account_create.add_argument("--name", required=True)
    account_create.add_argument("--set-default", action="store_true")
    account_import = account_subparsers.add_parser("import", help="Import an existing private key.")
    account_import.add_argument("--name", required=True)
    account_import.add_argument("--private-key", help="Hex private key. If omitted, vault will prompt.")
    account_import.add_argument("--set-default", action="store_true")
    account_watch = account_subparsers.add_parser("watch", help="Add a watch-only account by address.")
    account_watch.add_argument("--name", required=True)
    account_watch.add_argument("--address", required=True)
    account_watch.add_argument("--set-default", action="store_true")
    account_subparsers.add_parser("list", help="List stored accounts.")
    account_use = account_subparsers.add_parser("use", help="Select the default account.")
    account_use.add_argument("--name", required=True)

    network = subparsers.add_parser("network", help="Manage network definitions.")
    network_subparsers = network.add_subparsers(dest="network_command", required=True)
    network_add = network_subparsers.add_parser("add", help="Add or update a custom network.")
    network_add.add_argument("--name", required=True)
    network_add.add_argument("--rpc-url", required=True)
    network_add.add_argument("--chain-id", required=True, type=int)
    network_add.add_argument("--symbol", required=True)
    network_add.add_argument("--set-default", action="store_true")
    network_add_alchemy = network_subparsers.add_parser("add-alchemy", help="Add an Alchemy-backed network preset.")
    network_add_alchemy.add_argument("--preset", required=True)
    network_add_alchemy.add_argument("--name")
    network_add_alchemy.add_argument("--api-key-env", default="ALCHEMY_API_KEY")
    network_add_alchemy.add_argument("--set-default", action="store_true")
    network_add_anvil = network_subparsers.add_parser("add-anvil", help="Add a local Anvil network.")
    network_add_anvil.add_argument("--name", default="local")
    network_add_anvil.add_argument("--rpc-url", default="http://127.0.0.1:8545")
    network_add_anvil.add_argument("--chain-id", default=31337, type=int)
    network_add_anvil.add_argument("--symbol", default="ETH")
    network_add_anvil.add_argument("--set-default", action="store_true")
    network_subparsers.add_parser("list", help="List stored networks.")
    network_subparsers.add_parser("list-presets", help="List built-in Alchemy presets.")
    network_use = network_subparsers.add_parser("use", help="Select the default network.")
    network_use.add_argument("--name", required=True)

    address_book = subparsers.add_parser("address-book", help="Manage labeled recipient addresses.")
    address_book_subparsers = address_book.add_subparsers(dest="address_book_command", required=True)
    address_book_subparsers.add_parser("list", help="List address book entries.")
    address_book_add = address_book_subparsers.add_parser("add", help="Add or update an address book entry.")
    address_book_add.add_argument("--name", required=True)
    address_book_add.add_argument("--address", required=True)
    address_book_add.add_argument("--network", help="Optional network scope for this entry.")
    address_book_add.add_argument("--notes", help="Optional notes.")
    address_book_remove = address_book_subparsers.add_parser("remove", help="Remove an address book entry.")
    address_book_remove.add_argument("--name", required=True)

    backup = subparsers.add_parser("backup", help="Backup verification helpers.")
    backup_subparsers = backup.add_subparsers(dest="backup_command", required=True)
    backup_verify = backup_subparsers.add_parser("verify", help="Verify a stored encrypted keystore can be unlocked.")
    backup_verify.add_argument("--account", required=True)

    theme = subparsers.add_parser("theme", help="Manage TUI themes.")
    theme_subparsers = theme.add_subparsers(dest="theme_command", required=True)
    theme_subparsers.add_parser("list", help="List built-in TUI themes.")
    theme_subparsers.add_parser("show", help="Show the active TUI theme.")
    theme_use = theme_subparsers.add_parser("use", help="Set the active TUI theme for this profile.")
    theme_use.add_argument("--name", required=True)

    safety = subparsers.add_parser("safety", help="Safety helpers for profile separation.")
    safety_subparsers = safety.add_subparsers(dest="safety_command", required=True)
    safety_subparsers.add_parser("status", help="Inspect risky defaults and mixed dev/prod state.")
    safety_separate = safety_subparsers.add_parser("separate-dev", help="Move dev defaults out of prod.")
    safety_separate.add_argument("--prod-account", required=True)
    safety_separate.add_argument("--prod-network", required=True)
    safety_separate.add_argument("--dev-account", required=True)
    safety_separate.add_argument("--dev-network", required=True)
    safety_separate.add_argument("--overwrite", action="store_true")
    safety_separate.add_argument("--dry-run", action="store_true")

    doctor = subparsers.add_parser("doctor", help="Verify the selected RPC configuration.")
    doctor.add_argument("--network", help="Stored network name. Defaults to the configured default network.")

    sign_message = subparsers.add_parser("sign-message", help="Sign a plain-text message.")
    sign_message.add_argument("--account", help="Stored signer account. Defaults to the configured default account.")
    sign_message.add_argument("--message", required=True)

    sign_typed_data = subparsers.add_parser("sign-typed-data", help="Sign EIP-712 typed data from a JSON file.")
    sign_typed_data.add_argument("--account", help="Stored signer account. Defaults to the configured default account.")
    sign_typed_data.add_argument("--file", required=True)

    balance = subparsers.add_parser("balance", help="Fetch a balance.")
    balance.add_argument("--account", help="Stored account name. Defaults to the configured default account.")
    balance.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    balance.add_argument("--token", help="ERC-20 token address. Omit for the native asset.")

    lookup = subparsers.add_parser("lookup", help="Inspect an address, token contract, or generic contract.")
    lookup_subparsers = lookup.add_subparsers(dest="lookup_command", required=True)
    lookup_address = lookup_subparsers.add_parser("address", help="Inspect an address as an EOA or contract.")
    lookup_address.add_argument("--target", required=True, help="Raw address, stored account name, or address-book label.")
    lookup_address.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    lookup_token = lookup_subparsers.add_parser("token", help="Inspect a token-like contract.")
    lookup_token.add_argument("--target", required=True, help="Raw address, stored account name, or address-book label.")
    lookup_token.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    lookup_token.add_argument("--holder", help="Optional holder address, stored account name, or address-book label.")
    lookup_contract = lookup_subparsers.add_parser("contract", help="Inspect a generic contract with interface and proxy hints.")
    lookup_contract.add_argument("--target", required=True, help="Raw address, stored account name, or address-book label.")
    lookup_contract.add_argument("--network", help="Stored network name. Defaults to the configured default network.")

    contract = subparsers.add_parser("contract", help="Read from and write to contracts with explicit ABI input.")
    contract_subparsers = contract.add_subparsers(dest="contract_command", required=True)
    contract_read = contract_subparsers.add_parser("read", help="Execute a contract read call.")
    contract_read.add_argument("--target", required=True)
    contract_read.add_argument("--function", required=True)
    add_abi_arguments(contract_read)
    contract_read.add_argument("--args", help="JSON array of function arguments.")
    contract_read.add_argument("--network", help="Stored network name. Defaults to the configured default network.")

    contract_write = contract_subparsers.add_parser("write", help="Preview, simulate, or execute a contract write.")
    contract_write_subparsers = contract_write.add_subparsers(dest="contract_write_command", required=True)
    for name in ("preview", "simulate", "execute"):
        contract_write_action = contract_write_subparsers.add_parser(name, help=f"{name.title()} a contract write.")
        contract_write_action.add_argument("--target", required=True)
        contract_write_action.add_argument("--from-account", required=True)
        contract_write_action.add_argument("--function", required=True)
        add_abi_arguments(contract_write_action)
        contract_write_action.add_argument("--args", help="JSON array of function arguments.")
        contract_write_action.add_argument("--value", help="Optional native asset value to send with the call.")
        contract_write_action.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
        add_fee_arguments(contract_write_action)
        if name == "execute":
            contract_write_action.add_argument("--yes", action="store_true")

    token = subparsers.add_parser("token", help="Token-specific helpers built on contract primitives.")
    token_subparsers = token.add_subparsers(dest="token_command", required=True)
    token_allowance = token_subparsers.add_parser("allowance", help="Read ERC-20 allowance.")
    token_allowance.add_argument("--token", required=True)
    token_allowance.add_argument("--owner", required=True)
    token_allowance.add_argument("--spender", required=True)
    token_allowance.add_argument("--network", help="Stored network name. Defaults to the configured default network.")

    token_approve = token_subparsers.add_parser("approve", help="Preview, simulate, or execute ERC-20 approvals.")
    token_approve_subparsers = token_approve.add_subparsers(dest="token_approve_command", required=True)
    for name in ("preview", "simulate", "execute"):
        token_approve_action = token_approve_subparsers.add_parser(name, help=f"{name.title()} an ERC-20 approval.")
        token_approve_action.add_argument("--token", required=True)
        token_approve_action.add_argument("--from-account", required=True)
        token_approve_action.add_argument("--spender", required=True)
        token_approve_action.add_argument("--amount", required=True)
        token_approve_action.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
        add_fee_arguments(token_approve_action)
        if name == "execute":
            token_approve_action.add_argument("--yes", action="store_true")

    simulate = subparsers.add_parser("simulate", help="Simulate a transaction before broadcast.")
    simulate.add_argument("--from-account", help="Stored sender account. Defaults to the configured default account.")
    simulate.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    simulate.add_argument("--to", required=True)
    simulate.add_argument("--amount", required=True)
    simulate.add_argument("--token")
    add_fee_arguments(simulate)

    send = subparsers.add_parser("send", help="Sign and broadcast a transaction.")
    send.add_argument("--from-account", help="Stored sender account. Defaults to the configured default account.")
    send.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    send.add_argument("--to", required=True)
    send.add_argument("--amount", required=True)
    send.add_argument("--token")
    add_fee_arguments(send)
    send.add_argument("--yes", action="store_true")

    monitor = subparsers.add_parser("monitor", help="Observe wallet activity and balance changes.")
    monitor_subparsers = monitor.add_subparsers(dest="monitor_command", required=True)
    monitor_run = monitor_subparsers.add_parser("run", help="Poll account activity.")
    monitor_run.add_argument("--account", help="Stored account name. Defaults to the configured default account.")
    monitor_run.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    monitor_run.add_argument("--interval", type=int, default=10, help="Polling interval in seconds.")
    monitor_run.add_argument("--once", action="store_true", help="Perform a single poll and exit.")
    monitor_list = monitor_subparsers.add_parser("list-events", help="List monitor-written journal events.")
    monitor_list.add_argument("--account", help="Stored account name. Defaults to the configured default account.")
    monitor_list.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    monitor_list.add_argument("--limit", type=int, default=20)
    monitor_show = monitor_subparsers.add_parser("show-state", help="Show stored monitor state.")
    monitor_show.add_argument("--account", help="Stored account name. Defaults to the configured default account.")
    monitor_show.add_argument("--network", help="Stored network name. Defaults to the configured default network.")

    journal = subparsers.add_parser("journal", help="Inspect the local execution journal.")
    journal_subparsers = journal.add_subparsers(dest="journal_command", required=True)
    journal_subparsers.add_parser("list", help="List local journal entries.")
    journal_show = journal_subparsers.add_parser("show", help="Show a journal entry by id.")
    journal_show.add_argument("--id", dest="entry_id")
    journal_show.add_argument("--tx-hash", dest="entry_id")

    receipt = subparsers.add_parser("receipt", help="Fetch and store a transaction receipt.")
    receipt_subparsers = receipt.add_subparsers(dest="receipt_command", required=True)
    receipt_show = receipt_subparsers.add_parser("show", help="Show a transaction receipt.")
    receipt_show.add_argument("--tx-hash", required=True)
    receipt_show.add_argument("--network")

    policy = subparsers.add_parser("policy", help="Manage outbound policy rules.")
    policy_subparsers = policy.add_subparsers(dest="policy_command", required=True)
    policy_subparsers.add_parser("list", help="List stored policy rules.")
    policy_show = policy_subparsers.add_parser("show", help="Show effective policy.")
    policy_show.add_argument("--account")
    policy_set = policy_subparsers.add_parser("set", help="Set a policy rule.")
    policy_set.add_argument("--rule", required=True)
    policy_set.add_argument("--value", required=True)
    policy_set.add_argument("--account")
    policy_unset = policy_subparsers.add_parser("unset", help="Unset a policy rule.")
    policy_unset.add_argument("--rule", required=True)
    policy_unset.add_argument("--account")
    policy_explain = policy_subparsers.add_parser("explain", help="Explain whether an action is allowed.")
    policy_explain.add_argument("--account")
    policy_explain.add_argument("--network")
    policy_explain.add_argument("--to", required=True)
    policy_explain.add_argument("--amount", required=True)
    policy_explain.add_argument("--token")

    ui = subparsers.add_parser("ui", help="Launch the interactive terminal UI.")
    ui.add_argument("--profile", choices=["dev", "test", "prod"])
    ui.add_argument("--allow-prod", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = dispatch(args)
        if payload is not None:
            emit(payload, args.json)
        return 0
    except VaultError as exc:
        emit({"summary": "Command failed", "error": str(exc)}, args.json)
        return 1
    except KeyboardInterrupt:
        emit({"summary": "Command interrupted", "error": "Interrupted by user."}, args.json)
        return 130


def dispatch(args: argparse.Namespace) -> dict[str, Any] | None:
    service = VaultService(home=args.home)

    if args.command == "profile":
        if args.profile_command == "list":
            return service.list_profiles()
        if args.profile_command == "show":
            return service.show_profile()
        if args.profile_command == "use":
            return service.use_profile(args.name)

    if args.command == "account":
        if args.account_command == "create":
            passphrase = service._accounts().prompt_passphrase(confirm=True)
            return service.create_account(args.name, passphrase, set_default=args.set_default)
        if args.account_command == "import":
            accounts = service._accounts()
            private_key = args.private_key or accounts.prompt_private_key()
            passphrase = accounts.prompt_passphrase(confirm=True)
            return service.import_account(args.name, private_key, passphrase, set_default=args.set_default)
        if args.account_command == "watch":
            return service.add_watch_only_account(args.name, args.address, set_default=args.set_default)
        if args.account_command == "list":
            return service.list_accounts()
        if args.account_command == "use":
            return service.use_account(args.name)

    if args.command == "network":
        if args.network_command == "add":
            return service.add_network(
                name=args.name,
                rpc_url=args.rpc_url,
                chain_id=args.chain_id,
                symbol=args.symbol,
                set_default=args.set_default,
            )
        if args.network_command == "add-alchemy":
            return service.add_alchemy_network(
                preset=args.preset,
                api_key_env=args.api_key_env,
                name=args.name,
                set_default=args.set_default,
            )
        if args.network_command == "add-anvil":
            return service.add_anvil_network(
                name=args.name,
                rpc_url=args.rpc_url,
                chain_id=args.chain_id,
                symbol=args.symbol,
                set_default=args.set_default,
            )
        if args.network_command == "list":
            return service.list_networks()
        if args.network_command == "list-presets":
            return service.list_network_presets()
        if args.network_command == "use":
            return service.use_network(args.name)

    if args.command == "address-book":
        if args.address_book_command == "list":
            return service.list_address_book()
        if args.address_book_command == "add":
            return service.add_address_book_entry(
                name=args.name,
                address=args.address,
                network_scope=args.network,
                notes=args.notes,
            )
        if args.address_book_command == "remove":
            return service.remove_address_book_entry(args.name)

    if args.command == "theme":
        if args.theme_command == "list":
            return service.list_themes()
        if args.theme_command == "show":
            return service.show_theme()
        if args.theme_command == "use":
            return service.use_theme(args.name)

    if args.command == "backup":
        if args.backup_command == "verify":
            passphrase = service._accounts().prompt_passphrase()
            return service.verify_backup(args.account, passphrase)

    if args.command == "safety":
        if args.safety_command == "status":
            return service.safety_status()
        if args.safety_command == "separate-dev":
            return service.separate_dev(
                prod_account=args.prod_account,
                prod_network=args.prod_network,
                dev_account=args.dev_account,
                dev_network=args.dev_network,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
            )

    if args.command == "doctor":
        return service.doctor(args.network)

    if args.command == "sign-message":
        passphrase = service._accounts().prompt_passphrase()
        return service.sign_message(args.account, passphrase, args.message)

    if args.command == "sign-typed-data":
        passphrase = service._accounts().prompt_passphrase()
        with open(args.file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return service.sign_typed_data(args.account, passphrase, payload)

    if args.command == "balance":
        return service.balance(account_name=args.account, network_name=args.network, token_address=args.token)

    if args.command == "lookup":
        if args.lookup_command == "address":
            return service.lookup_address(target=args.target, network_name=args.network)
        if args.lookup_command == "token":
            return service.lookup_token(target=args.target, network_name=args.network, holder=args.holder)
        if args.lookup_command == "contract":
            return service.lookup_contract(target=args.target, network_name=args.network)

    if args.command == "contract":
        if args.contract_command == "read":
            return service.contract_read(
                target=args.target,
                function_name=args.function,
                abi_file=args.abi_file,
                abi_fragment=args.abi_fragment,
                args_json=args.args,
                network_name=args.network,
            )
        if args.contract_command == "write":
            if args.contract_write_command == "preview":
                return service.preview_contract_write(
                    from_account_name=args.from_account,
                    target=args.target,
                    function_name=args.function,
                    abi_file=args.abi_file,
                    abi_fragment=args.abi_fragment,
                    args_json=args.args,
                    value=args.value,
                    network_name=args.network,
                    nonce=args.nonce,
                    gas_limit=args.gas_limit,
                    gas_price_gwei=args.gas_price,
                    max_fee_per_gas_gwei=args.max_fee_per_gas,
                    max_priority_fee_per_gas_gwei=args.max_priority_fee_per_gas,
                )
            if args.contract_write_command == "simulate":
                return service.simulate_contract_write(
                    from_account_name=args.from_account,
                    target=args.target,
                    function_name=args.function,
                    abi_file=args.abi_file,
                    abi_fragment=args.abi_fragment,
                    args_json=args.args,
                    value=args.value,
                    network_name=args.network,
                    nonce=args.nonce,
                    gas_limit=args.gas_limit,
                    gas_price_gwei=args.gas_price,
                    max_fee_per_gas_gwei=args.max_fee_per_gas,
                    max_priority_fee_per_gas_gwei=args.max_priority_fee_per_gas,
                )
            if args.contract_write_command == "execute":
                preview = service.preview_contract_write(
                    from_account_name=args.from_account,
                    target=args.target,
                    function_name=args.function,
                    abi_file=args.abi_file,
                    abi_fragment=args.abi_fragment,
                    args_json=args.args,
                    value=args.value,
                    network_name=args.network,
                    nonce=args.nonce,
                    gas_limit=args.gas_limit,
                    gas_price_gwei=args.gas_price,
                    max_fee_per_gas_gwei=args.max_fee_per_gas,
                    max_priority_fee_per_gas_gwei=args.max_priority_fee_per_gas,
                )
                if not args.yes:
                    confirm_transaction(preview)
                passphrase = service._accounts().prompt_passphrase()
                return service.execute_contract_write(passphrase=passphrase, preview=preview)

    if args.command == "token":
        if args.token_command == "allowance":
            return service.token_allowance(
                token_target=args.token,
                owner=args.owner,
                spender=args.spender,
                network_name=args.network,
            )
        if args.token_command == "approve":
            if args.token_approve_command == "preview":
                return service.preview_token_approve(
                    from_account_name=args.from_account,
                    token_target=args.token,
                    spender=args.spender,
                    amount=args.amount,
                    network_name=args.network,
                    nonce=args.nonce,
                    gas_limit=args.gas_limit,
                    gas_price_gwei=args.gas_price,
                    max_fee_per_gas_gwei=args.max_fee_per_gas,
                    max_priority_fee_per_gas_gwei=args.max_priority_fee_per_gas,
                )
            if args.token_approve_command == "simulate":
                return service.simulate_token_approve(
                    from_account_name=args.from_account,
                    token_target=args.token,
                    spender=args.spender,
                    amount=args.amount,
                    network_name=args.network,
                    nonce=args.nonce,
                    gas_limit=args.gas_limit,
                    gas_price_gwei=args.gas_price,
                    max_fee_per_gas_gwei=args.max_fee_per_gas,
                    max_priority_fee_per_gas_gwei=args.max_priority_fee_per_gas,
                )
            if args.token_approve_command == "execute":
                preview = service.preview_token_approve(
                    from_account_name=args.from_account,
                    token_target=args.token,
                    spender=args.spender,
                    amount=args.amount,
                    network_name=args.network,
                    nonce=args.nonce,
                    gas_limit=args.gas_limit,
                    gas_price_gwei=args.gas_price,
                    max_fee_per_gas_gwei=args.max_fee_per_gas,
                    max_priority_fee_per_gas_gwei=args.max_priority_fee_per_gas,
                )
                if not args.yes:
                    confirm_transaction(preview)
                passphrase = service._accounts().prompt_passphrase()
                return service.execute_token_approve(passphrase=passphrase, preview=preview)

    if args.command == "simulate":
        return service.simulate_send(
            from_account_name=args.from_account,
            network_name=args.network,
            recipient=args.to,
            amount=args.amount,
            token_address=args.token,
            nonce=args.nonce,
            gas_limit=args.gas_limit,
            gas_price_gwei=args.gas_price,
            max_fee_per_gas_gwei=args.max_fee_per_gas,
            max_priority_fee_per_gas_gwei=args.max_priority_fee_per_gas,
        )

    if args.command == "send":
        preview = service.preview_send(
            from_account_name=args.from_account,
            network_name=args.network,
            recipient=args.to,
            amount=args.amount,
            token_address=args.token,
            nonce=args.nonce,
            gas_limit=args.gas_limit,
            gas_price_gwei=args.gas_price,
            max_fee_per_gas_gwei=args.max_fee_per_gas,
            max_priority_fee_per_gas_gwei=args.max_priority_fee_per_gas,
        )
        if not args.yes:
            confirm_transaction(preview)
        passphrase = service._accounts().prompt_passphrase()
        return service.execute_send(
            passphrase=passphrase,
            from_account_name=args.from_account,
            network_name=args.network,
            recipient=args.to,
            amount=args.amount,
            token_address=args.token,
            nonce=args.nonce,
            gas_limit=args.gas_limit,
            gas_price_gwei=args.gas_price,
            max_fee_per_gas_gwei=args.max_fee_per_gas,
            max_priority_fee_per_gas_gwei=args.max_priority_fee_per_gas,
        )

    if args.command == "monitor":
        if args.monitor_command == "show-state":
            return service.monitor_show_state(args.account, args.network)
        if args.monitor_command == "list-events":
            return service.monitor_list_events(args.account, args.network, args.limit)
        if args.monitor_command == "run":
            if args.once:
                return service.monitor_poll(args.account, args.network)
            return run_monitor_loop(service, args.account, args.network, max(1, args.interval), args.json)

    if args.command == "journal":
        if args.journal_command == "list":
            return service.list_journal()
        if args.journal_command == "show":
            if not args.entry_id:
                raise ValidationError("Provide `--id` for the journal entry.")
            return service.show_journal_entry(args.entry_id)

    if args.command == "receipt":
        if args.receipt_command == "show":
            return service.show_receipt(args.tx_hash, args.network)

    if args.command == "policy":
        if args.policy_command == "list":
            return service.list_policies()
        if args.policy_command == "show":
            return service.show_policy(args.account)
        if args.policy_command == "set":
            return service.set_policy_rule(args.rule, args.value, args.account)
        if args.policy_command == "unset":
            return service.unset_policy_rule(args.rule, args.account)
        if args.policy_command == "explain":
            return service.explain_policy_action(
                account_name=args.account,
                network_name=args.network,
                recipient=args.to,
                amount=args.amount,
                token_address=args.token,
            )

    if args.command == "ui":
        return launch_ui(args.home, args.profile, args.allow_prod)

    raise ValidationError(f"Unhandled command: {args.command}")


def run_monitor_loop(
    service: VaultService,
    account_name: str | None,
    network_name: str | None,
    interval: int,
    as_json: bool,
) -> dict[str, Any]:
    while True:
        payload = service.monitor_poll(account_name=account_name, network_name=network_name)
        emit(payload, as_json)
        time.sleep(interval)


def confirm_transaction(preview: dict[str, Any]) -> None:
    if preview["asset_type"] == "erc20":
        asset = preview["token_address"]
        quantity = preview["amount"]
    elif preview["asset_type"] == "erc20_approval":
        asset = preview["token_address"]
        quantity = preview["amount"]
    elif preview["asset_type"] == "contract":
        asset = preview.get("contract_function") or "contract_write"
        quantity = preview.get("value") or "0"
    else:
        asset = preview["symbol"]
        quantity = preview["amount"]
    print(f"Profile: {preview['profile']}")
    print(f"Network: {preview['network_name']}")
    print(f"From:    {preview['from_address']}")
    if preview.get("recipient_name"):
        print(f"To:      {preview['to_address']} ({preview['recipient_name']})")
    else:
        print(f"To:      {preview['to_address']}")
    print(f"Asset:   {asset}")
    if preview["asset_type"] == "contract":
        print(f"Function: {preview.get('contract_function')}")
        print(f"Value:    {quantity}")
    else:
        print(f"Amount:  {quantity}")
    print(f"Nonce:   {preview['nonce']}")
    print(f"Gas:     {preview['gas_limit']}")
    print(f"Fee:     {preview['fee_model']} max={preview['max_fee_cost_wei']} wei")
    if preview["requires_strong_confirmation"]:
        suffix = preview["to_address"][-6:]
        amount = quantity
        answer = input(f"Type {suffix} to confirm this protected transaction: ").strip()
        if answer != suffix:
            raise ValidationError("Protected transaction cancelled.")
        amount_answer = input(f"Retype the amount ({amount}) to broadcast: ").strip()
        if amount_answer != amount:
            raise ValidationError("Protected transaction cancelled.")
        return
    answer = input("Type YES to broadcast this transaction: ").strip()
    if answer != "YES":
        raise ValidationError("Transaction cancelled.")


def launch_ui(home: str | None, profile: str | None, allow_prod: bool) -> dict[str, Any]:
    resolved_profile = profile
    if not resolved_profile:
        current_service = VaultService(home=home)
        resolved_profile = "dev" if current_service.profile_name == "prod" else current_service.profile_name
    if resolved_profile == "prod" and not allow_prod:
        raise ValidationError("Refusing to open the UI on `prod` without `--allow-prod`.")
    try:
        from vault.tui import run_tui
    except ImportError as exc:
        raise ValidationError(
            "Textual is required for `vault ui`. Run `pip install -e .` after adding the dependency."
        ) from exc
    run_tui(home=home, profile=resolved_profile, allow_prod=allow_prod)
    return {"summary": f"UI closed for profile {resolved_profile}"}


if __name__ == "__main__":
    sys.exit(main())
