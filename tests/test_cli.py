from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vault.address_book import AddressBookManager
from vault.cli import build_parser, launch_ui
from vault.config import VaultError, resolve_paths, save_json, set_active_profile_name
from vault.evm import redact_rpc_url
from vault.networks import NetworkManager
from vault.output import format_human
from vault.service import VaultService


class ParserTests(unittest.TestCase):
    def test_json_flag_and_send_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--json",
                "send",
                "--from-account",
                "alice",
                "--network",
                "sepolia",
                "--to",
                "0x1111111111111111111111111111111111111111",
                "--amount",
                "0.5",
                "--yes",
            ]
        )
        self.assertTrue(args.json)
        self.assertEqual(args.command, "send")
        self.assertEqual(args.from_account, "alice")
        self.assertEqual(args.network, "sepolia")
        self.assertEqual(args.amount, "0.5")
        self.assertTrue(args.yes)

    def test_add_alchemy_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "network",
                "add-alchemy",
                "--preset",
                "eth-sepolia",
                "--name",
                "sepolia",
                "--api-key-env",
                "ALCHEMY_API_KEY",
            ]
        )
        self.assertEqual(args.command, "network")
        self.assertEqual(args.network_command, "add-alchemy")
        self.assertEqual(args.preset, "eth-sepolia")
        self.assertEqual(args.api_key_env, "ALCHEMY_API_KEY")

    def test_add_anvil_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "network",
                "add-anvil",
                "--name",
                "local",
                "--set-default",
            ]
        )
        self.assertEqual(args.command, "network")
        self.assertEqual(args.network_command, "add-anvil")
        self.assertEqual(args.name, "local")
        self.assertTrue(args.set_default)

    def test_profile_use_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["profile", "use", "--name", "dev"])
        self.assertEqual(args.command, "profile")
        self.assertEqual(args.profile_command, "use")
        self.assertEqual(args.name, "dev")

    def test_address_book_add_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["address-book", "add", "--name", "friend", "--address", "0x1111111111111111111111111111111111111111"]
        )
        self.assertEqual(args.command, "address-book")
        self.assertEqual(args.address_book_command, "add")
        self.assertEqual(args.name, "friend")

    def test_ui_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["ui"])
        self.assertEqual(args.command, "ui")

    def test_watch_account_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["account", "watch", "--name", "observer", "--address", "0x1111111111111111111111111111111111111111"])
        self.assertEqual(args.command, "account")
        self.assertEqual(args.account_command, "watch")
        self.assertEqual(args.name, "observer")

    def test_simulate_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["simulate", "--to", "0x1111111111111111111111111111111111111111", "--amount", "1"])
        self.assertEqual(args.command, "simulate")
        self.assertEqual(args.amount, "1")

    def test_policy_set_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["policy", "set", "--rule", "blocked_networks", "--value", "mainnet"])
        self.assertEqual(args.command, "policy")
        self.assertEqual(args.policy_command, "set")
        self.assertEqual(args.rule, "blocked_networks")

    def test_theme_use_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["theme", "use", "--name", "nord"])
        self.assertEqual(args.command, "theme")
        self.assertEqual(args.theme_command, "use")
        self.assertEqual(args.name, "nord")

    def test_safety_separate_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "safety",
                "separate-dev",
                "--prod-account",
                "main",
                "--prod-network",
                "mainnet",
                "--dev-account",
                "local-dev",
                "--dev-network",
                "local",
                "--dry-run",
            ]
        )
        self.assertEqual(args.command, "safety")
        self.assertEqual(args.safety_command, "separate-dev")
        self.assertTrue(args.dry_run)

    def test_safe_register_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "safe",
                "register",
                "--name",
                "team-safe",
                "--address",
                "0x1111111111111111111111111111111111111111",
                "--network",
                "mainnet",
                "--service-url",
                "https://safe.example",
            ]
        )
        self.assertEqual(args.command, "safe")
        self.assertEqual(args.safe_command, "register")
        self.assertEqual(args.name, "team-safe")
        self.assertEqual(args.network, "mainnet")

    def test_aa_register_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "aa",
                "register",
                "--name",
                "session-account",
                "--sender",
                "0x1111111111111111111111111111111111111111",
                "--network",
                "sepolia",
                "--owner-account",
                "main",
                "--entrypoint",
                "0x5ff137d4b0fdcd49dca30c7cf57e578a026d2789",
            ]
        )
        self.assertEqual(args.command, "aa")
        self.assertEqual(args.aa_command, "register")
        self.assertEqual(args.owner_account, "main")

    def test_smart_account_use_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["smart-account", "use", "--name", "team-safe"])
        self.assertEqual(args.command, "smart-account")
        self.assertEqual(args.smart_account_command, "use")
        self.assertEqual(args.name, "team-safe")


class NetworkStoreTests(unittest.TestCase):
    def test_add_network_sets_default_when_first_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NetworkManager(resolve_paths(temp_dir))
            payload = manager.add_network(
                name="sepolia",
                rpc_url="https://rpc.example",
                chain_id=11155111,
                symbol="ETH",
            )
            self.assertEqual(payload["default_network"], "sepolia")
            listed = manager.list_networks()
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["networks"][0]["name"], "sepolia")

    def test_add_alchemy_network_resolves_rpc_url_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NetworkManager(resolve_paths(temp_dir))
            manager.add_alchemy_network(
                preset="eth-sepolia",
                api_key_env="ALCHEMY_API_KEY",
                name="sepolia",
            )
            listed = manager.list_networks()
            self.assertEqual(listed["networks"][0]["provider"], "alchemy")
            self.assertEqual(listed["networks"][0]["alchemy_preset"], "eth-sepolia")
            self.assertEqual(listed["networks"][0]["api_key_env"], "ALCHEMY_API_KEY")

            original = os.environ.get("ALCHEMY_API_KEY")
            os.environ["ALCHEMY_API_KEY"] = "test-key"
            try:
                resolved = manager.get_network("sepolia")
            finally:
                if original is None:
                    os.environ.pop("ALCHEMY_API_KEY", None)
                else:
                    os.environ["ALCHEMY_API_KEY"] = original

            self.assertEqual(resolved["chain_id"], 11155111)
            self.assertEqual(resolved["rpc_url"], "https://eth-sepolia.g.alchemy.com/v2/test-key")

    def test_add_anvil_network_uses_local_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NetworkManager(resolve_paths(temp_dir))
            payload = manager.add_anvil_network(set_default=True)
            self.assertEqual(payload["name"], "local")
            self.assertEqual(payload["provider"], "anvil")
            self.assertEqual(payload["chain_id"], 31337)
            self.assertEqual(payload["rpc_url"], "http://127.0.0.1:8545")
            self.assertEqual(payload["default_network"], "local")


class ProfileTests(unittest.TestCase):
    def test_prod_uses_legacy_home_when_existing_wallet_data_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            save_json(temp_path / "config.json", {"default_account": "main"})
            paths = resolve_paths(temp_dir, "prod")
            self.assertTrue(paths.using_legacy_profile_home)
            self.assertEqual(paths.home, temp_path)

    def test_profiles_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prod_manager = NetworkManager(resolve_paths(temp_dir, "prod"))
            prod_manager.add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)

            dev_manager = NetworkManager(resolve_paths(temp_dir, "dev"))
            dev_manager.add_anvil_network(set_default=True)

            prod_networks = prod_manager.list_networks()
            dev_networks = dev_manager.list_networks()

            self.assertEqual(prod_networks["count"], 1)
            self.assertEqual(prod_networks["networks"][0]["name"], "mainnet")
            self.assertEqual(dev_networks["count"], 1)
            self.assertEqual(dev_networks["networks"][0]["name"], "local")

    def test_profile_use_updates_global_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = VaultService(home=temp_dir)
            payload = service.use_profile("dev")
            self.assertEqual(payload["name"], "dev")
            self.assertEqual(resolve_paths(temp_dir).profile_name, "dev")


class AddressBookTests(unittest.TestCase):
    def test_address_book_entries_are_profile_local(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prod_book = AddressBookManager(resolve_paths(temp_dir, "prod"))
            dev_book = AddressBookManager(resolve_paths(temp_dir, "dev"))
            prod_book.add_entry("friend", "0x1111111111111111111111111111111111111111")
            dev_entries = dev_book.list_entries()
            prod_entries = prod_book.list_entries()
            self.assertEqual(prod_entries["count"], 1)
            self.assertEqual(dev_entries["count"], 0)

    def test_address_book_resolution_honors_network_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AddressBookManager(resolve_paths(temp_dir, "test"))
            manager.add_entry(
                "faucet",
                "0x1111111111111111111111111111111111111111",
                network_scope="sepolia",
            )
            resolved = manager.resolve("faucet", "sepolia")
            self.assertEqual(resolved["name"], "faucet")
            with self.assertRaises(Exception):
                manager.resolve("faucet", "mainnet")


class ServiceTests(unittest.TestCase):
    def test_theme_is_profile_local(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prod_service = VaultService(home=temp_dir, profile="prod")
            dev_service = VaultService(home=temp_dir, profile="dev")

            prod_payload = prod_service.use_theme("nord")
            dev_payload = dev_service.show_theme()

            self.assertEqual(prod_payload["name"], "nord")
            self.assertEqual(dev_payload["name"], "vault")

    def test_context_summary_surfaces_default_account_and_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            save_json(
                Path(temp_dir) / "accounts" / "main.json",
                {
                    "version": 1,
                    "name": "main",
                    "address": "0x1111111111111111111111111111111111111111",
                    "source": "created",
                    "created_at": "2026-04-21T00:00:00+00:00",
                },
            )
            save_json(Path(temp_dir) / "config.json", {"default_account": "main"})
            network_manager = NetworkManager(resolve_paths(temp_dir, "prod"))
            network_manager.add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)

            service = VaultService(home=temp_dir, profile="prod")
            payload = service.context_summary()

            self.assertEqual(payload["profile"], "prod")
            self.assertEqual(payload["default_account"]["name"], "main")
            self.assertEqual(payload["default_network"]["name"], "mainnet")
            self.assertTrue(payload["is_protected_profile"])

    def test_context_summary_surfaces_default_smart_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            save_json(
                Path(temp_dir) / "accounts" / "owner.json",
                {
                    "version": 1,
                    "name": "owner",
                    "address": "0x1111111111111111111111111111111111111111",
                    "source": "created",
                    "created_at": "2026-04-21T00:00:00+00:00",
                },
            )
            save_json(Path(temp_dir) / "config.json", {"default_account": "owner"})
            network_manager = NetworkManager(resolve_paths(temp_dir, "prod"))
            network_manager.add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)

            service = VaultService(home=temp_dir, profile="prod")
            with patch("vault.service.SafeClient") as safe_client:
                safe_client.return_value.get_safe_info.return_value = {
                    "address": "0x2222222222222222222222222222222222222222",
                    "owners": ["0x1111111111111111111111111111111111111111"],
                    "threshold": 1,
                    "nonce": 0,
                }
                service.register_safe_account(
                    name="team-safe",
                    address="0x2222222222222222222222222222222222222222",
                    network_name="mainnet",
                    set_default=True,
                )
            payload = service.context_summary()
            self.assertEqual(payload["default_smart_account"]["name"], "team-safe")
            self.assertEqual(payload["smart_account_count"], 1)

    def test_safe_owner_check_uses_owner_address_not_account_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            save_json(
                Path(temp_dir) / "accounts" / "owner.json",
                {
                    "version": 1,
                    "name": "owner",
                    "address": "0x1111111111111111111111111111111111111111",
                    "source": "imported",
                    "account_kind": "local",
                    "signer_type": "local",
                    "can_sign": True,
                },
            )
            save_json(Path(temp_dir) / "config.json", {"default_account": "owner"})
            network_manager = NetworkManager(resolve_paths(temp_dir, "prod"))
            network_manager.add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)

            service = VaultService(home=temp_dir, profile="prod")
            with patch("vault.service.SafeClient") as safe_client:
                safe_client.return_value.get_safe_info.return_value = {
                    "address": "0x2222222222222222222222222222222222222222",
                    "owners": ["0x1111111111111111111111111111111111111111"],
                    "threshold": 1,
                    "nonce": 0,
                }
                service.register_safe_account(
                    name="team-safe",
                    address="0x2222222222222222222222222222222222222222",
                    network_name="mainnet",
                    set_default=True,
                )

            config = service.show_smart_account("team-safe")
            service._ensure_safe_owner(config, "owner")

    def test_register_erc4337_account_sets_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            save_json(
                Path(temp_dir) / "accounts" / "owner.json",
                {
                    "version": 1,
                    "name": "owner",
                    "address": "0x1111111111111111111111111111111111111111",
                    "source": "imported",
                    "account_kind": "local",
                    "signer_type": "local",
                    "can_sign": True,
                },
            )
            save_json(Path(temp_dir) / "config.json", {"default_account": "owner"})
            network_manager = NetworkManager(resolve_paths(temp_dir, "prod"))
            network_manager.add_network("sepolia", "https://rpc.example", 11155111, "ETH", set_default=True)

            service = VaultService(home=temp_dir, profile="prod")
            payload = service.register_erc4337_account(
                name="aa-main",
                sender="0x2222222222222222222222222222222222222222",
                network_name="sepolia",
                owner_account="owner",
                entrypoint="0x5ff137d4b0fdcd49dca30c7cf57e578a026d2789",
                bundler_url="https://bundler.example",
                set_default=True,
            )
            self.assertEqual(payload["name"], "aa-main")
            self.assertEqual(payload["default_smart_account"], "aa-main")
            listed = service.list_smart_accounts()
            self.assertEqual(listed["count"], 1)

    def test_balance_snapshot_returns_error_payload_for_wallet_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            save_json(
                Path(temp_dir) / "accounts" / "main.json",
                {
                    "version": 1,
                    "name": "main",
                    "address": "0x1111111111111111111111111111111111111111",
                    "source": "created",
                    "created_at": "2026-04-21T00:00:00+00:00",
                },
            )
            save_json(Path(temp_dir) / "config.json", {"default_account": "main"})
            network_manager = NetworkManager(resolve_paths(temp_dir, "prod"))
            network_manager.add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)

            service = VaultService(home=temp_dir, profile="prod")
            with patch.object(service, "balance", side_effect=VaultError("rpc unavailable")):
                payload = service.balance_snapshot()

            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["account_name"], "main")
            self.assertEqual(payload["network_name"], "mainnet")
            self.assertEqual(payload["message"], "rpc unavailable")

    def test_execute_send_uses_prepared_preview_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = VaultService(home=temp_dir, profile="prod")

            class FakeNetworks:
                def get_network(self, name: str | None) -> dict[str, object]:
                    return {"name": name or "mainnet", "chain_id": 1, "symbol": "ETH"}

            class FakeSigner:
                last_preview: dict[str, object] | None = None
                can_sign = True
                signer_type = "local"

                def send_prepared(self, passphrase: str, preview: dict[str, object], network: dict[str, object]) -> dict[str, object]:
                    FakeSigner.last_preview = preview
                    payload = dict(preview)
                    payload["network"] = network["name"]
                    payload["transaction_hash"] = "0xabc123"
                    payload["submitted_at"] = "2026-04-21T00:00:00+00:00"
                    payload.pop("tx", None)
                    return payload

            preview = {
                "profile": "prod",
                "account_name": "main",
                "account_kind": "local",
                "signer_type": "local",
                "can_sign": True,
                "network_name": "mainnet",
                "recipient_name": None,
                "requires_strong_confirmation": True,
                "requires_simulation": False,
                "asset_type": "native",
                "symbol": "ETH",
                "from_address": "0x1111111111111111111111111111111111111111",
                "to_address": "0x2222222222222222222222222222222222222222",
                "amount": "0.5",
                "nonce": 1,
                "gas_limit": 21000,
                "fee_model": "eip1559",
                "max_fee_cost_wei": "42000000000000",
                "estimated_total_cost_wei": "500042000000000000",
                "tx": {"nonce": 1},
            }

            with patch.object(service, "_networks", return_value=FakeNetworks()):
                with patch.object(service, "_journal"):
                    with patch("vault.service.resolve_signer", return_value=FakeSigner()):
                        payload = service.execute_send(passphrase="secret", preview=preview)

            self.assertEqual(payload["transaction_hash"], "0xabc123")
            self.assertEqual(FakeSigner.last_preview, preview)

    def test_watch_only_account_cannot_sign(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = VaultService(home=temp_dir, profile="dev")
            service.add_watch_only_account("observer", "0x1111111111111111111111111111111111111111", set_default=True)

            with self.assertRaises(VaultError):
                service.sign_message("observer", "secret", "hello")

    def test_policy_blocks_preview_send(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            save_json(
                Path(temp_dir) / "accounts" / "main.json",
                {
                    "version": 1,
                    "name": "main",
                    "address": "0x1111111111111111111111111111111111111111",
                    "source": "imported",
                    "account_kind": "local",
                    "signer_type": "local",
                    "can_sign": True,
                },
            )
            save_json(Path(temp_dir) / "config.json", {"default_account": "main"})
            network_manager = NetworkManager(resolve_paths(temp_dir, "prod"))
            network_manager.add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)

            service = VaultService(home=temp_dir, profile="prod")
            service.set_policy_rule("blocked_networks", "mainnet")

            with self.assertRaises(VaultError):
                service.preview_send(
                    from_account_name="main",
                    network_name="mainnet",
                    recipient="0x2222222222222222222222222222222222222222",
                    amount="0.5",
                )

    def test_preview_send_sets_strong_confirmation_for_prod(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            save_json(
                Path(temp_dir) / "accounts" / "main.json",
                {
                    "version": 1,
                    "name": "main",
                    "address": "0x1111111111111111111111111111111111111111",
                    "source": "imported",
                },
            )
            save_json(Path(temp_dir) / "config.json", {"default_account": "main"})
            network_manager = NetworkManager(resolve_paths(temp_dir, "prod"))
            network_manager.add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)

            class FakeClient:
                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def prepare_native_transfer(self, **_: object) -> dict[str, object]:
                    return {
                        "network": "mainnet",
                        "network_name": "mainnet",
                        "chain_id": 1,
                        "asset_type": "native",
                        "symbol": "ETH",
                        "from_address": "0x1111111111111111111111111111111111111111",
                        "to_address": "0x2222222222222222222222222222222222222222",
                        "amount": "0.5",
                        "amount_wei": "500000000000000000",
                        "nonce": 0,
                        "gas_limit": 21000,
                        "fee_model": "eip1559",
                        "max_fee_cost_wei": "42000000000000",
                        "estimated_total_cost_wei": "500042000000000000",
                        "tx": {},
                    }

            with patch("vault.service.EVMClient", FakeClient):
                service = VaultService(home=temp_dir, profile="prod")
                preview = service.preview_send(
                    from_account_name="main",
                    network_name="mainnet",
                    recipient="0x2222222222222222222222222222222222222222",
                    amount="0.5",
                )
            self.assertTrue(preview["requires_strong_confirmation"])
            self.assertEqual(preview["profile"], "prod")

    def test_separate_dev_dry_run_returns_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = VaultService(home=temp_dir)
            payload = service.separate_dev(
                prod_account="main",
                prod_network="mainnet",
                dev_account="local-dev",
                dev_network="local",
                dry_run=True,
            )
            self.assertEqual(payload["summary"], "Planned dev separation")
            self.assertEqual(payload["actions"][0]["action"], "set_prod_default_account")

    def test_separate_dev_copies_dev_assets_and_sets_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prod_paths = resolve_paths(temp_dir, "prod")
            save_json(
                prod_paths.accounts_dir / "main.json",
                {
                    "version": 1,
                    "name": "main",
                    "address": "0x1111111111111111111111111111111111111111",
                    "source": "created",
                    "created_at": "2026-04-21T00:00:00+00:00",
                    "crypto": {"ciphertext": "x", "nonce": "x", "salt": "x"},
                },
            )
            save_json(
                prod_paths.accounts_dir / "local-dev.json",
                {
                    "version": 1,
                    "name": "local-dev",
                    "address": "0x2222222222222222222222222222222222222222",
                    "source": "imported",
                    "created_at": "2026-04-21T00:00:00+00:00",
                    "crypto": {"ciphertext": "x", "nonce": "x", "salt": "x"},
                },
            )
            save_json(prod_paths.config_file, {"default_account": "local-dev"})
            network_manager = NetworkManager(prod_paths)
            network_manager.add_network("mainnet", "https://rpc.example", 1, "ETH")
            network_manager.add_anvil_network(name="local", set_default=True)

            service = VaultService(home=temp_dir, profile="prod")
            payload = service.separate_dev(
                prod_account="main",
                prod_network="mainnet",
                dev_account="local-dev",
                dev_network="local",
            )
            self.assertEqual(payload["prod_default_account"], "main")
            self.assertEqual(payload["dev_default_account"], "local-dev")
            dev_accounts = VaultService(home=temp_dir, profile="dev").list_accounts()
            self.assertEqual(dev_accounts["default_account"], "local-dev")
            self.assertEqual(dev_accounts["count"], 1)


class UiSafetyTests(unittest.TestCase):
    def test_launch_ui_refuses_prod_without_allow_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(Exception):
                launch_ui(temp_dir, "prod", False)


class OutputTests(unittest.TestCase):
    def test_human_output_renders_list_rows_on_separate_lines(self) -> None:
        rendered = format_human(
            {
                "summary": "Found 1 account(s)",
                "accounts": [
                    {
                        "name": "alice",
                        "address": "0x1111111111111111111111111111111111111111",
                        "is_default": True,
                    }
                ],
            }
        )
        self.assertIn("Accounts:\n- ", rendered)
        self.assertIn("name=alice", rendered)

    def test_redact_rpc_url_masks_api_key_segment(self) -> None:
        rendered = redact_rpc_url("https://eth-sepolia.g.alchemy.com/v2/secret-api-key")
        self.assertEqual(rendered, "https://eth-sepolia.g.alchemy.com/v2/***")

    def test_prefixed_hex_normalizes_bare_hex(self) -> None:
        from vault.evm import prefixed_hex

        self.assertEqual(prefixed_hex(bytes.fromhex("ab" * 4)), "0x" + ("ab" * 4))


class JournalTests(unittest.TestCase):
    def test_normalize_tx_hash_accepts_bare_hex(self) -> None:
        from vault.journal import normalize_tx_hash

        bare = "ab" * 32
        self.assertEqual(normalize_tx_hash(bare), f"0x{bare}")


if __name__ == "__main__":
    unittest.main()
