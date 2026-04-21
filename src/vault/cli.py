from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from vault.config import ValidationError, VaultError
from vault.output import emit
from vault.service import VaultService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vault", description="Manage EVM wallet accounts from the terminal.")
    parser.add_argument("--home", help="Override the vault data directory.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    profile = subparsers.add_parser("profile", help="Manage isolated wallet profiles.")
    profile_subparsers = profile.add_subparsers(dest="profile_command", required=True)

    profile_list = profile_subparsers.add_parser("list", help="List profiles.")
    profile_list.set_defaults(handler="profile_list")

    profile_show = profile_subparsers.add_parser("show", help="Show the active profile.")
    profile_show.set_defaults(handler="profile_show")

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
    network_add_alchemy.add_argument("--preset", required=True, help="Alchemy preset like eth-sepolia or base-mainnet.")
    network_add_alchemy.add_argument("--name", help="Local network name. Defaults to the preset name.")
    network_add_alchemy.add_argument(
        "--api-key-env",
        default="ALCHEMY_API_KEY",
        help="Environment variable containing the Alchemy API key.",
    )
    network_add_alchemy.add_argument("--set-default", action="store_true")

    network_add_anvil = network_subparsers.add_parser("add-anvil", help="Add a local Anvil network.")
    network_add_anvil.add_argument("--name", default="local", help="Local network name. Defaults to `local`.")
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

    smart_account = subparsers.add_parser("smart-account", help="Manage smart-account registry entries.")
    smart_account_subparsers = smart_account.add_subparsers(dest="smart_account_command", required=True)
    smart_account_subparsers.add_parser("list", help="List registered smart accounts.")
    smart_account_show = smart_account_subparsers.add_parser("show", help="Show a smart account.")
    smart_account_show.add_argument("--name")
    smart_account_use = smart_account_subparsers.add_parser("use", help="Set the default smart account.")
    smart_account_use.add_argument("--name", required=True)
    smart_account_remove = smart_account_subparsers.add_parser("remove", help="Remove a registered smart account.")
    smart_account_remove.add_argument("--name", required=True)

    safe = subparsers.add_parser("safe", help="Manage Safe smart accounts.")
    safe_subparsers = safe.add_subparsers(dest="safe_command", required=True)
    safe_register = safe_subparsers.add_parser("register", help="Register an existing Safe.")
    safe_register.add_argument("--name", required=True)
    safe_register.add_argument("--address", required=True)
    safe_register.add_argument("--network", required=True)
    safe_register.add_argument("--service-url")
    safe_register.add_argument("--entrypoint")
    safe_register.add_argument("--set-default", action="store_true")
    safe_sync = safe_subparsers.add_parser("sync", help="Refresh Safe owners and threshold from chain.")
    safe_sync.add_argument("--name")
    safe_create = safe_subparsers.add_parser("create", help="Submit a Safe proxy creation transaction.")
    safe_create.add_argument("--signer-account", required=True)
    safe_create.add_argument("--network", required=True)
    safe_create.add_argument("--singleton", required=True)
    safe_create.add_argument("--factory", required=True)
    safe_create.add_argument("--fallback-handler", required=True)
    safe_create.add_argument("--owners", required=True, help="Comma-separated owner account names or addresses.")
    safe_create.add_argument("--threshold", required=True, type=int)
    safe_create.add_argument("--salt-nonce", required=True, type=int)
    safe_pending = safe_subparsers.add_parser("pending", help="List pending Safe transactions.")
    safe_pending.add_argument("--name")
    safe_tx = safe_subparsers.add_parser("tx", help="Show a pending Safe transaction.")
    safe_tx.add_argument("--safe-tx-hash", required=True)
    safe_tx.add_argument("--name")
    safe_propose = safe_subparsers.add_parser("propose", help="Propose a Safe transaction.")
    safe_propose.add_argument("--name")
    safe_propose.add_argument("--signer-account", required=True)
    safe_propose.add_argument("--to", required=True)
    safe_propose.add_argument("--value", default="0")
    safe_propose.add_argument("--data", default="0x")
    safe_propose.add_argument("--operation", default=0, type=int)
    safe_propose.add_argument("--nonce", type=int)
    safe_propose.add_argument("--origin")
    safe_owner_add = safe_subparsers.add_parser("owner-add", help="Propose adding a Safe owner.")
    safe_owner_add.add_argument("--name")
    safe_owner_add.add_argument("--signer-account", required=True)
    safe_owner_add.add_argument("--owner-address", required=True)
    safe_owner_add.add_argument("--threshold", type=int)
    safe_owner_add.add_argument("--nonce", type=int)
    safe_owner_remove = safe_subparsers.add_parser("owner-remove", help="Propose removing a Safe owner.")
    safe_owner_remove.add_argument("--name")
    safe_owner_remove.add_argument("--signer-account", required=True)
    safe_owner_remove.add_argument("--prev-owner", required=True)
    safe_owner_remove.add_argument("--owner-address", required=True)
    safe_owner_remove.add_argument("--threshold", required=True, type=int)
    safe_owner_remove.add_argument("--nonce", type=int)
    safe_threshold = safe_subparsers.add_parser("threshold-set", help="Propose changing Safe threshold.")
    safe_threshold.add_argument("--name")
    safe_threshold.add_argument("--signer-account", required=True)
    safe_threshold.add_argument("--threshold", required=True, type=int)
    safe_threshold.add_argument("--nonce", type=int)
    safe_confirm = safe_subparsers.add_parser("confirm", help="Confirm a pending Safe transaction.")
    safe_confirm.add_argument("--name")
    safe_confirm.add_argument("--signer-account", required=True)
    safe_confirm.add_argument("--safe-tx-hash", required=True)
    safe_execute = safe_subparsers.add_parser("execute", help="Execute a confirmed Safe transaction.")
    safe_execute.add_argument("--name")
    safe_execute.add_argument("--signer-account", required=True)
    safe_execute.add_argument("--safe-tx-hash", required=True)

    aa = subparsers.add_parser("aa", help="Manage ERC-4337 smart accounts.")
    aa_subparsers = aa.add_subparsers(dest="aa_command", required=True)
    aa_register = aa_subparsers.add_parser("register", help="Register an ERC-4337 smart account.")
    aa_register.add_argument("--name", required=True)
    aa_register.add_argument("--sender", required=True)
    aa_register.add_argument("--network", required=True)
    aa_register.add_argument("--owner-account", required=True)
    aa_register.add_argument("--entrypoint", required=True)
    aa_register.add_argument("--version", default="0.6")
    aa_register.add_argument("--factory")
    aa_register.add_argument("--factory-data")
    aa_register.add_argument("--bundler-url")
    aa_register.add_argument("--paymaster-url")
    aa_register.add_argument("--set-default", action="store_true")
    aa_prepare = aa_subparsers.add_parser("prepare", help="Prepare a user operation.")
    aa_prepare.add_argument("--name")
    aa_prepare.add_argument("--to", required=True)
    aa_prepare.add_argument("--value", default="0")
    aa_prepare.add_argument("--data", default="0x")
    aa_prepare.add_argument("--nonce")
    aa_prepare.add_argument("--signature")
    aa_sign = aa_subparsers.add_parser("sign", help="Sign a prepared user operation from a JSON file.")
    aa_sign.add_argument("--name")
    aa_sign.add_argument("--file", required=True)
    aa_simulate = aa_subparsers.add_parser("simulate", help="Simulate a prepared user operation from a JSON file.")
    aa_simulate.add_argument("--name")
    aa_simulate.add_argument("--file", required=True)
    aa_submit = aa_subparsers.add_parser("submit", help="Submit a signed user operation from a JSON file.")
    aa_submit.add_argument("--name")
    aa_submit.add_argument("--file", required=True)
    aa_status = aa_subparsers.add_parser("status", help="Fetch status for a submitted user operation.")
    aa_status.add_argument("--name")
    aa_status.add_argument("--user-operation-hash", required=True)

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
    safety_separate.add_argument("--prod-account", required=True, help="The intended default account for prod.")
    safety_separate.add_argument("--prod-network", required=True, help="The intended default network for prod.")
    safety_separate.add_argument("--dev-account", required=True, help="An existing account in prod to copy into dev.")
    safety_separate.add_argument("--dev-network", required=True, help="An existing network in prod to copy into dev.")
    safety_separate.add_argument("--overwrite", action="store_true", help="Overwrite existing dev entries if present.")
    safety_separate.add_argument("--dry-run", action="store_true", help="Show the planned actions without changing data.")

    doctor = subparsers.add_parser("doctor", help="Verify the selected RPC configuration.")
    doctor.add_argument("--network", help="Stored network name. Defaults to the configured default network.")

    sign_message = subparsers.add_parser("sign-message", help="Sign a plain-text message.")
    sign_message.add_argument("--account", help="Stored signer account. Defaults to the configured default account.")
    sign_message.add_argument("--message", required=True)

    sign_typed_data = subparsers.add_parser("sign-typed-data", help="Sign EIP-712 typed data from a JSON file.")
    sign_typed_data.add_argument("--account", help="Stored signer account. Defaults to the configured default account.")
    sign_typed_data.add_argument("--file", required=True, help="Path to JSON payload containing the full typed data object.")

    balance = subparsers.add_parser("balance", help="Fetch a balance.")
    balance.add_argument("--account", help="Stored account name. Defaults to the configured default account.")
    balance.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    balance.add_argument("--token", help="ERC-20 token address. Omit for the native asset.")

    simulate = subparsers.add_parser("simulate", help="Simulate a transaction before broadcast.")
    simulate.add_argument("--from-account", help="Stored sender account. Defaults to the configured default account.")
    simulate.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    simulate.add_argument("--to", required=True, help="Recipient address or address-book label.")
    simulate.add_argument("--amount", required=True, help="Human-readable decimal amount.")
    simulate.add_argument("--token", help="ERC-20 token address. Omit for the native asset.")
    simulate.add_argument("--nonce", type=int)
    simulate.add_argument("--gas-limit", type=int)
    simulate.add_argument("--gas-price", help="Legacy gas price in gwei.")
    simulate.add_argument("--max-fee-per-gas", help="EIP-1559 max fee per gas in gwei.")
    simulate.add_argument("--max-priority-fee-per-gas", help="EIP-1559 max priority fee per gas in gwei.")

    send = subparsers.add_parser("send", help="Sign and broadcast a transaction.")
    send.add_argument("--from-account", help="Stored sender account. Defaults to the configured default account.")
    send.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    send.add_argument("--to", required=True, help="Recipient address or address-book label.")
    send.add_argument("--amount", required=True, help="Human-readable decimal amount.")
    send.add_argument("--token", help="ERC-20 token address. Omit for the native asset.")
    send.add_argument("--nonce", type=int)
    send.add_argument("--gas-limit", type=int)
    send.add_argument("--gas-price", help="Legacy gas price in gwei.")
    send.add_argument("--max-fee-per-gas", help="EIP-1559 max fee per gas in gwei.")
    send.add_argument("--max-priority-fee-per-gas", help="EIP-1559 max priority fee per gas in gwei.")
    send.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    journal = subparsers.add_parser("journal", help="Inspect the local execution journal.")
    journal_subparsers = journal.add_subparsers(dest="journal_command", required=True)
    journal_subparsers.add_parser("list", help="List local journal entries.")
    journal_show = journal_subparsers.add_parser("show", help="Show a journal entry by transaction hash.")
    journal_show.add_argument("--tx-hash", required=True)

    receipt = subparsers.add_parser("receipt", help="Fetch and store a transaction receipt.")
    receipt_subparsers = receipt.add_subparsers(dest="receipt_command", required=True)
    receipt_show = receipt_subparsers.add_parser("show", help="Show a transaction receipt.")
    receipt_show.add_argument("--tx-hash", required=True)
    receipt_show.add_argument("--network", help="Network name. Optional if the tx is already in the local journal.")

    policy = subparsers.add_parser("policy", help="Manage outbound policy rules.")
    policy_subparsers = policy.add_subparsers(dest="policy_command", required=True)
    policy_subparsers.add_parser("list", help="List stored policy rules.")
    policy_show = policy_subparsers.add_parser("show", help="Show effective policy.")
    policy_show.add_argument("--account", help="Optional account override scope.")
    policy_set = policy_subparsers.add_parser("set", help="Set a policy rule.")
    policy_set.add_argument("--rule", required=True)
    policy_set.add_argument("--value", required=True)
    policy_set.add_argument("--account", help="Optional account override scope.")
    policy_unset = policy_subparsers.add_parser("unset", help="Unset a policy rule.")
    policy_unset.add_argument("--rule", required=True)
    policy_unset.add_argument("--account", help="Optional account override scope.")
    policy_explain = policy_subparsers.add_parser("explain", help="Explain whether an action is allowed.")
    policy_explain.add_argument("--account", help="Stored sender account. Defaults to the configured default account.")
    policy_explain.add_argument("--network", help="Stored network name. Defaults to the configured default network.")
    policy_explain.add_argument("--to", required=True, help="Recipient address or address-book label.")
    policy_explain.add_argument("--amount", required=True, help="Human-readable decimal amount.")
    policy_explain.add_argument("--token", help="ERC-20 token address. Omit for the native asset.")

    ui = subparsers.add_parser("ui", help="Launch the interactive terminal UI.")
    ui.add_argument("--profile", choices=["dev", "test", "prod"], help="Open the UI against a specific profile.")
    ui.add_argument("--allow-prod", action="store_true", help="Allow opening the UI directly on the prod profile.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = dispatch(args)
        emit(payload, args.json)
        return 0
    except VaultError as exc:
        emit({"summary": "Command failed", "error": str(exc)}, args.json)
        return 1
    except KeyboardInterrupt:
        emit({"summary": "Command interrupted", "error": "Interrupted by user."}, args.json)
        return 130


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
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

    if args.command == "smart-account":
        if args.smart_account_command == "list":
            return service.list_smart_accounts()
        if args.smart_account_command == "show":
            return service.show_smart_account(args.name)
        if args.smart_account_command == "use":
            return service.use_smart_account(args.name)
        if args.smart_account_command == "remove":
            return service.remove_smart_account(args.name)

    if args.command == "safe":
        if args.safe_command == "register":
            return service.register_safe_account(
                name=args.name,
                address=args.address,
                network_name=args.network,
                service_url=args.service_url,
                entrypoint=args.entrypoint,
                set_default=args.set_default,
            )
        if args.safe_command == "sync":
            return service.sync_safe_account(args.name)
        if args.safe_command == "create":
            passphrase = service._accounts().prompt_passphrase()
            owners = [item.strip() for item in args.owners.split(",") if item.strip()]
            resolved_owners = []
            for owner in owners:
                if owner.startswith("0x"):
                    resolved_owners.append(owner)
                else:
                    resolved_owners.append(service._resolve_account_metadata(owner)["address"])
            return service.create_safe_account(
                signer_account=args.signer_account,
                passphrase=passphrase,
                network_name=args.network,
                singleton=args.singleton,
                factory=args.factory,
                fallback_handler=args.fallback_handler,
                owners=resolved_owners,
                threshold=args.threshold,
                salt_nonce=args.salt_nonce,
            )
        if args.safe_command == "pending":
            return service.list_safe_pending_transactions(args.name)
        if args.safe_command == "tx":
            return service.show_safe_pending_transaction(args.safe_tx_hash, args.name)
        if args.safe_command == "propose":
            passphrase = service._accounts().prompt_passphrase()
            return service.propose_safe_transaction(
                name=args.name,
                signer_account=args.signer_account,
                passphrase=passphrase,
                to=args.to,
                value=args.value,
                data=args.data,
                operation=args.operation,
                nonce=args.nonce,
                origin=args.origin,
            )
        if args.safe_command == "owner-add":
            passphrase = service._accounts().prompt_passphrase()
            return service.propose_safe_add_owner(
                name=args.name,
                signer_account=args.signer_account,
                passphrase=passphrase,
                owner_address=args.owner_address,
                threshold=args.threshold,
                nonce=args.nonce,
            )
        if args.safe_command == "owner-remove":
            passphrase = service._accounts().prompt_passphrase()
            return service.propose_safe_remove_owner(
                name=args.name,
                signer_account=args.signer_account,
                passphrase=passphrase,
                prev_owner=args.prev_owner,
                owner_address=args.owner_address,
                threshold=args.threshold,
                nonce=args.nonce,
            )
        if args.safe_command == "threshold-set":
            passphrase = service._accounts().prompt_passphrase()
            return service.propose_safe_change_threshold(
                name=args.name,
                signer_account=args.signer_account,
                passphrase=passphrase,
                threshold=args.threshold,
                nonce=args.nonce,
            )
        if args.safe_command == "confirm":
            passphrase = service._accounts().prompt_passphrase()
            return service.confirm_safe_transaction(
                name=args.name,
                signer_account=args.signer_account,
                passphrase=passphrase,
                safe_tx_hash=args.safe_tx_hash,
            )
        if args.safe_command == "execute":
            passphrase = service._accounts().prompt_passphrase()
            return service.execute_safe_transaction(
                name=args.name,
                signer_account=args.signer_account,
                passphrase=passphrase,
                safe_tx_hash=args.safe_tx_hash,
            )

    if args.command == "aa":
        if args.aa_command == "register":
            return service.register_erc4337_account(
                name=args.name,
                sender=args.sender,
                network_name=args.network,
                owner_account=args.owner_account,
                entrypoint=args.entrypoint,
                version=args.version,
                factory=args.factory,
                factory_data=args.factory_data,
                bundler_url=args.bundler_url,
                paymaster_url=args.paymaster_url,
                set_default=args.set_default,
            )
        if args.aa_command == "prepare":
            return service.prepare_user_operation(
                name=args.name,
                to=args.to,
                value=args.value,
                data=args.data,
                nonce=args.nonce,
                signature=args.signature,
            )
        if args.aa_command == "sign":
            passphrase = service._accounts().prompt_passphrase()
            with open(args.file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return service.sign_user_operation(args.name, passphrase, payload)
        if args.aa_command == "simulate":
            with open(args.file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return service.simulate_user_operation(args.name, payload)
        if args.aa_command == "submit":
            with open(args.file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return service.submit_user_operation(args.name, payload)
        if args.aa_command == "status":
            return service.user_operation_status(args.name, args.user_operation_hash)

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
        return service.balance(
            account_name=args.account,
            network_name=args.network,
            token_address=args.token,
        )

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
            confirm_send(preview)
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

    if args.command == "journal":
        if args.journal_command == "list":
            return service.list_journal()
        if args.journal_command == "show":
            return service.show_journal_entry(args.tx_hash)

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


def confirm_send(preview: dict[str, Any]) -> None:
    asset = preview["token_address"] if preview["asset_type"] == "erc20" else preview["symbol"]
    print(f"Profile: {preview['profile']}")
    print(f"Network: {preview['network_name']}")
    print(f"From:    {preview['from_address']}")
    if preview.get("recipient_name"):
        print(f"To:      {preview['to_address']} ({preview['recipient_name']})")
    else:
        print(f"To:      {preview['to_address']}")
    print(f"Asset:   {asset}")
    print(f"Amount:  {preview['amount']}")
    print(f"Nonce:   {preview['nonce']}")
    print(f"Gas:     {preview['gas_limit']}")
    print(f"Fee:     {preview['fee_model']} max={preview['max_fee_cost_wei']} wei")
    if preview["requires_strong_confirmation"]:
        suffix = preview["to_address"][-6:]
        amount = preview["amount"]
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
