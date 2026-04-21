from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from textual.containers import HorizontalScroll, VerticalScroll
    from textual.widgets import Static, TabbedContent, Tabs
    from vault.tui import VaultTUI
    TEXTUAL_AVAILABLE = True
except ModuleNotFoundError:
    HorizontalScroll = object
    VerticalScroll = object
    Static = object
    TabbedContent = object
    Tabs = object
    VaultTUI = None
    TEXTUAL_AVAILABLE = False

from vault.address_book import AddressBookManager
from vault.cli import build_parser, launch_ui
from vault.config import VaultError, resolve_paths, save_json
from vault.evm import redact_rpc_url
from vault.journal import JournalManager, normalize_event_id, normalize_tx_hash
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
        self.assertTrue(args.yes)

    def test_monitor_run_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["monitor", "run", "--account", "main", "--network", "sepolia", "--once"])
        self.assertEqual(args.command, "monitor")
        self.assertEqual(args.monitor_command, "run")
        self.assertEqual(args.account, "main")
        self.assertEqual(args.network, "sepolia")
        self.assertTrue(args.once)

    def test_monitor_list_events_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["monitor", "list-events", "--limit", "5"])
        self.assertEqual(args.command, "monitor")
        self.assertEqual(args.monitor_command, "list-events")
        self.assertEqual(args.limit, 5)

    def test_lookup_address_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["lookup", "address", "--target", "main", "--network", "sepolia"])
        self.assertEqual(args.command, "lookup")
        self.assertEqual(args.lookup_command, "address")
        self.assertEqual(args.target, "main")
        self.assertEqual(args.network, "sepolia")

    def test_lookup_token_command_parse_with_holder(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["lookup", "token", "--target", "usdc", "--network", "mainnet", "--holder", "treasury"])
        self.assertEqual(args.command, "lookup")
        self.assertEqual(args.lookup_command, "token")
        self.assertEqual(args.target, "usdc")
        self.assertEqual(args.network, "mainnet")
        self.assertEqual(args.holder, "treasury")

    def test_lookup_contract_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["lookup", "contract", "--target", "0x1111111111111111111111111111111111111111"])
        self.assertEqual(args.command, "lookup")
        self.assertEqual(args.lookup_command, "contract")
        self.assertEqual(args.target, "0x1111111111111111111111111111111111111111")

    def test_contract_read_command_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["contract", "read", "--target", "friend", "--abi-file", "erc20.json", "--function", "balanceOf", "--args", "[\"0x1\"]"]
        )
        self.assertEqual(args.command, "contract")
        self.assertEqual(args.contract_command, "read")
        self.assertEqual(args.target, "friend")
        self.assertEqual(args.abi_file, "erc20.json")
        self.assertEqual(args.function, "balanceOf")

    def test_contract_write_preview_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "contract",
                "write",
                "preview",
                "--target",
                "friend",
                "--from-account",
                "main",
                "--abi-fragment",
                "{\"name\":\"setX\",\"type\":\"function\",\"inputs\":[{\"type\":\"uint256\"}],\"outputs\":[]}",
                "--function",
                "setX",
                "--args",
                "[1]",
                "--value",
                "0.1",
            ]
        )
        self.assertEqual(args.contract_command, "write")
        self.assertEqual(args.contract_write_command, "preview")
        self.assertEqual(args.from_account, "main")
        self.assertEqual(args.value, "0.1")

    def test_token_allowance_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["token", "allowance", "--token", "usdc", "--owner", "main", "--spender", "router"])
        self.assertEqual(args.command, "token")
        self.assertEqual(args.token_command, "allowance")
        self.assertEqual(args.owner, "main")
        self.assertEqual(args.spender, "router")

    def test_token_approve_execute_parse(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["token", "approve", "execute", "--token", "usdc", "--from-account", "main", "--spender", "router", "--amount", "1", "--yes"]
        )
        self.assertEqual(args.command, "token")
        self.assertEqual(args.token_command, "approve")
        self.assertEqual(args.token_approve_command, "execute")
        self.assertTrue(args.yes)

    def test_removed_safe_command_is_gone(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["safe", "register"])

    def test_removed_aa_command_is_gone(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["aa", "register"])

    def test_removed_smart_account_command_is_gone(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["smart-account", "list"])


@unittest.skipUnless(TEXTUAL_AVAILABLE, "textual is not installed")
class TUITests(unittest.IsolatedAsyncioTestCase):
    async def test_mount_with_journal_entries_keeps_selection_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = JournalManager(resolve_paths(temp_dir))
            entry = manager.record_event(
                "monitor:main:local:incoming:2026-04-21T05:12:46+00:00",
                "monitor_transaction_observed",
                {
                    "kind": "observation",
                    "origin": "monitor",
                    "event_type": "incoming_transaction_observed",
                    "status": "observed",
                    "profile": "dev",
                    "network": "local",
                    "account_name": "observer",
                    "address": "0x1111111111111111111111111111111111111111",
                    "created_at": "2026-04-21T05:12:46+00:00",
                    "details": {"block_number": 1},
                },
            )

            app = VaultTUI(home=temp_dir)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                journal_list = app.query_one("#journal_list")
                self.assertEqual(journal_list.index, 0)
                self.assertEqual(app.selected_journal_id, entry["id"])

    async def test_scrollable_layout_containers_allow_vertical_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = VaultTUI(home=temp_dir)
            async with app.run_test(size=(140, 40)) as pilot:
                scrollable_selectors = [
                    "#sidebar",
                    "#main",
                    ".detail-column",
                    ".send-form-column",
                    ".send-preview-column",
                ]
                for selector in scrollable_selectors:
                    widgets = list(app.query(selector))
                    self.assertGreater(len(widgets), 0, selector)
                    for widget in widgets:
                        self.assertIsInstance(widget, VerticalScroll, selector)
                        self.assertEqual(widget.styles.overflow_y, "auto", selector)

                tab_panes = list(app.query("TabPane"))
                self.assertGreater(len(tab_panes), 0)
                for widget in tab_panes:
                    self.assertEqual(str(widget.styles.height), "1fr")
                    self.assertEqual(widget.styles.overflow_y, "auto")

                app.action_show_accounts()
                await pilot.pause()
                active_detail = [widget for widget in app.query(".detail-column") if widget.display and widget.size.height > 0][0]
                self.assertGreater(active_detail.max_scroll_y, 0)

    async def test_horizontal_overflow_containers_exist_for_buttons_and_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = VaultTUI(home=temp_dir)
            async with app.run_test(size=(90, 30)) as pilot:
                await pilot.pause()

                for selector in [".quick-row", ".form-actions"]:
                    widgets = list(app.query(selector))
                    self.assertGreater(len(widgets), 0, selector)
                    for widget in widgets:
                        self.assertIsInstance(widget, HorizontalScroll, selector)
                        self.assertEqual(widget.styles.overflow_x, "auto", selector)

                sidebar = app.query_one("#sidebar")
                main = app.query_one("#main")
                self.assertEqual(sidebar.styles.overflow_x, "auto")
                self.assertEqual(main.styles.overflow_x, "auto")

                tabs = app.query_one(Tabs)
                self.assertEqual(tabs.styles.overflow_x, "scroll")
                self.assertEqual(tabs.styles.overflow_y, "hidden")

    async def test_lookup_tab_is_reachable_and_renders_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = VaultTUI(home=temp_dir)
            payload = {
                "summary": "Lookup address for 0x1111111111111111111111111111111111111111 on local",
                "profile": "prod",
                "network": "local",
                "chain_id": 31337,
                "query": "main",
                "query_kind": "account",
                "address": "0x1111111111111111111111111111111111111111",
                "classification": "eoa",
                "nonce": 1,
                "native_balance": {"symbol": "ETH", "balance_wei": "1", "balance": "0.000000000000000001"},
                "code_present": False,
                "code_size_bytes": 0,
                "detected_interfaces": [],
                "proxy_hints": {"implementation": None, "admin": None, "beacon": None, "is_proxy": False},
            }
            with patch.object(app.service, "lookup_address", return_value=payload):
                async with app.run_test(size=(140, 40)) as pilot:
                    app.action_show_lookup()
                    await pilot.pause()
                    self.assertEqual(app.query_one("#tabs", TabbedContent).active, "tab_lookup")
                    app.set_value("lookup_target", "main")
                    app.run_safe(app.lookup_address)
                    await pilot.pause()
                    self.assertEqual(app.last_lookup_result, payload)
                    rendered = str(app.query_one("#lookup_result_view", Static).renderable)
                    self.assertIn("Lookup address", rendered)
                    self.assertIn("0x1111111111111111111111111111111111111111", rendered)

    async def test_lookup_token_form_passes_target_holder_and_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = VaultTUI(home=temp_dir)
            payload = {
                "summary": "Lookup token for 0x2222222222222222222222222222222222222222 on local",
                "profile": "prod",
                "network": "local",
                "chain_id": 31337,
                "query": "friend",
                "query_kind": "address_book",
                "address": "0x2222222222222222222222222222222222222222",
                "token_standard": "erc20",
                "name": "Example",
                "symbol": "EXP",
                "decimals": 18,
                "total_supply": "1000",
                "is_contract": True,
                "code_size_bytes": 512,
                "detected_interfaces": ["erc20"],
                "proxy_hints": {"implementation": None, "admin": None, "beacon": None, "is_proxy": False},
                "holder": {
                    "query": "main",
                    "query_kind": "account",
                    "address": "0x1111111111111111111111111111111111111111",
                    "balance_lookup_supported": True,
                    "balance_raw": "5",
                    "balance": "0.000000000000000005",
                    "note": None,
                },
            }
            with patch.object(app.service, "lookup_token", return_value=payload) as lookup_token:
                async with app.run_test(size=(140, 40)) as pilot:
                    app.set_value("lookup_target", "friend")
                    app.set_value("lookup_network", "local")
                    app.set_value("lookup_holder", "main")
                    app.run_safe(app.lookup_token)
                    await pilot.pause()
                    lookup_token.assert_called_once_with(target="friend", network_name="local", holder="main")

    async def test_contract_tab_is_reachable_and_uses_service(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = VaultTUI(home=temp_dir)
            preview = {
                "summary": "Prepared contract write on local",
                "profile": "prod",
                "network_name": "local",
                "chain_id": 31337,
                "account_name": "main",
                "account_kind": "watch_only",
                "signer_type": "watch_only",
                "can_sign": False,
                "query": "friend",
                "query_kind": "address_book",
                "recipient_name": "friend",
                "from_address": "0x1111111111111111111111111111111111111111",
                "to_address": "0x2222222222222222222222222222222222222222",
                "asset_type": "contract",
                "contract_function": "setValue",
                "args": [1],
                "value": "0",
                "value_wei": "0",
                "data": "0x1234",
                "nonce": 1,
                "gas_limit": 50000,
                "fee_model": "eip1559",
                "max_fee_cost_wei": "1",
                "estimated_total_cost_wei": "1",
                "requires_strong_confirmation": False,
                "requires_simulation": False,
                "policy_findings": ["Action allowed by policy."],
                "tx": {"nonce": 1},
            }
            with patch.object(app.service, "preview_contract_write", return_value=preview) as preview_contract_write:
                async with app.run_test(size=(140, 40)) as pilot:
                    app.action_show_contracts()
                    await pilot.pause()
                    self.assertEqual(app.query_one("#tabs", TabbedContent).active, "tab_contracts")
                    app.set_value("contract_target", "friend")
                    app.set_value("contract_from_account", "main")
                    app.set_value("contract_network", "local")
                    app.set_value("contract_abi_fragment", "{\"name\":\"setValue\",\"type\":\"function\",\"inputs\":[{\"type\":\"uint256\"}],\"outputs\":[]}")
                    app.set_value("contract_function", "setValue")
                    app.set_value("contract_args", "[1]")
                    app.run_safe(app.preview_contract_write)
                    await pilot.pause()
                    preview_contract_write.assert_called_once()
                    rendered = str(app.query_one("#contract_preview_view", Static).renderable)
                    self.assertIn("setValue", rendered)


class NetworkStoreTests(unittest.TestCase):
    def test_add_network_sets_default_when_first_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NetworkManager(resolve_paths(temp_dir))
            payload = manager.add_network("sepolia", "https://rpc.example", 11155111, "ETH")
            self.assertEqual(payload["default_network"], "sepolia")
            listed = manager.list_networks()
            self.assertEqual(listed["count"], 1)

    def test_add_alchemy_network_resolves_rpc_url_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NetworkManager(resolve_paths(temp_dir))
            manager.add_alchemy_network("eth-sepolia", "ALCHEMY_API_KEY", name="sepolia")
            original = os.environ.get("ALCHEMY_API_KEY")
            os.environ["ALCHEMY_API_KEY"] = "test-key"
            try:
                resolved = manager.get_network("sepolia")
            finally:
                if original is None:
                    os.environ.pop("ALCHEMY_API_KEY", None)
                else:
                    os.environ["ALCHEMY_API_KEY"] = original
            self.assertEqual(resolved["rpc_url"], "https://eth-sepolia.g.alchemy.com/v2/test-key")

    def test_add_anvil_network_uses_local_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NetworkManager(resolve_paths(temp_dir))
            payload = manager.add_anvil_network(set_default=True)
            self.assertEqual(payload["name"], "local")
            self.assertEqual(payload["default_network"], "local")

    def test_network_outputs_redact_secret_bearing_rpc_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NetworkManager(resolve_paths(temp_dir))
            payload = manager.add_network(
                "mainnet",
                "https://user:secret@rpc.example/v1/really-secret-key?apiKey=topsecret",
                1,
                "ETH",
                set_default=True,
            )
            self.assertEqual(payload["rpc_url"], "https://rpc.example/v1/***?apiKey=%2A%2A%2A")
            listed = manager.list_networks()
            self.assertEqual(listed["networks"][0]["rpc_url"], "https://rpc.example/v1/***?apiKey=%2A%2A%2A")


class ProfileTests(unittest.TestCase):
    def test_profiles_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prod_manager = NetworkManager(resolve_paths(temp_dir, "prod"))
            prod_manager.add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)
            dev_manager = NetworkManager(resolve_paths(temp_dir, "dev"))
            dev_manager.add_anvil_network(set_default=True)
            self.assertEqual(prod_manager.list_networks()["count"], 1)
            self.assertEqual(dev_manager.list_networks()["networks"][0]["name"], "local")

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
            self.assertEqual(prod_book.list_entries()["count"], 1)
            self.assertEqual(dev_book.list_entries()["count"], 0)

    def test_address_book_resolution_honors_network_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AddressBookManager(resolve_paths(temp_dir, "test"))
            manager.add_entry("faucet", "0x1111111111111111111111111111111111111111", network_scope="sepolia")
            resolved = manager.resolve("faucet", "sepolia")
            self.assertEqual(resolved["name"], "faucet")
            with self.assertRaises(Exception):
                manager.resolve("faucet", "mainnet")


class ServiceTests(unittest.TestCase):
    def seed_lookup_store(self, temp_dir: str) -> None:
        save_json(
            Path(temp_dir) / "accounts" / "main.json",
            {
                "version": 1,
                "name": "main",
                "address": "0x1111111111111111111111111111111111111111",
                "source": "watch_only",
                "created_at": "2026-04-21T00:00:00+00:00",
                "account_kind": "watch_only",
                "signer_type": "watch_only",
                "can_sign": False,
            },
        )
        save_json(Path(temp_dir) / "config.json", {"default_account": "main"})
        NetworkManager(resolve_paths(temp_dir, "prod")).add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)
        AddressBookManager(resolve_paths(temp_dir, "prod")).add_entry(
            "friend",
            "0x2222222222222222222222222222222222222222",
            network_scope="mainnet",
        )

    def test_theme_is_profile_local(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prod_service = VaultService(home=temp_dir, profile="prod")
            dev_service = VaultService(home=temp_dir, profile="dev")
            prod_service.use_theme("nord")
            self.assertEqual(dev_service.show_theme()["name"], "vault")

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
            NetworkManager(resolve_paths(temp_dir, "prod")).add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)
            payload = VaultService(home=temp_dir, profile="prod").context_summary()
            self.assertEqual(payload["default_account"]["name"], "main")
            self.assertEqual(payload["default_network"]["name"], "mainnet")
            self.assertNotIn("default_smart_account", payload)

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
            NetworkManager(resolve_paths(temp_dir, "prod")).add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)
            service = VaultService(home=temp_dir, profile="prod")
            with patch.object(service, "balance", side_effect=VaultError("rpc unavailable")):
                payload = service.balance_snapshot()
            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["message"], "rpc unavailable")

    def test_lookup_address_resolves_raw_address_and_reports_eoa(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)

            class FakeClient:
                last_address: str | None = None
                last_network: dict[str, object] | None = None

                def __init__(self, network: dict[str, object]) -> None:
                    FakeClient.last_network = network

                def inspect_address(self, address: str) -> dict[str, object]:
                    FakeClient.last_address = address
                    return {
                        "address": address,
                        "classification": "eoa",
                        "nonce": 3,
                        "code_present": False,
                        "code_size_bytes": 0,
                        "detected_interfaces": [],
                        "proxy_hints": {"implementation": None, "admin": None, "beacon": None, "is_proxy": False},
                    }

                def get_native_balance(self, address: str) -> dict[str, object]:
                    return {
                        "symbol": "ETH",
                        "balance_wei": "42",
                        "balance": "0.000000000000000042",
                    }

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").lookup_address(
                    "0x3333333333333333333333333333333333333333",
                    "mainnet",
                )
            self.assertEqual(payload["query_kind"], "raw")
            self.assertEqual(payload["classification"], "eoa")
            self.assertEqual(payload["nonce"], 3)
            self.assertEqual(payload["native_balance"]["balance_wei"], "42")
            self.assertEqual(FakeClient.last_address, "0x3333333333333333333333333333333333333333")
            self.assertEqual(FakeClient.last_network["name"], "mainnet")

    def test_lookup_address_resolves_account_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)

            class FakeClient:
                last_address: str | None = None

                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def inspect_address(self, address: str) -> dict[str, object]:
                    FakeClient.last_address = address
                    return {
                        "address": address,
                        "classification": "eoa",
                        "nonce": 1,
                        "code_present": False,
                        "code_size_bytes": 0,
                        "detected_interfaces": [],
                        "proxy_hints": {"implementation": None, "admin": None, "beacon": None, "is_proxy": False},
                    }

                def get_native_balance(self, address: str) -> dict[str, object]:
                    return {"symbol": "ETH", "balance_wei": "1", "balance": "0.000000000000000001"}

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").lookup_address("main", "mainnet")
            self.assertEqual(payload["query_kind"], "account")
            self.assertEqual(payload["address"], "0x1111111111111111111111111111111111111111")
            self.assertEqual(FakeClient.last_address, "0x1111111111111111111111111111111111111111")

    def test_lookup_address_resolves_address_book_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)

            class FakeClient:
                last_address: str | None = None

                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def inspect_address(self, address: str) -> dict[str, object]:
                    FakeClient.last_address = address
                    return {
                        "address": address,
                        "classification": "contract",
                        "nonce": 7,
                        "code_present": True,
                        "code_size_bytes": 512,
                        "detected_interfaces": ["erc20"],
                        "proxy_hints": {"implementation": None, "admin": None, "beacon": None, "is_proxy": False},
                    }

                def get_native_balance(self, address: str) -> dict[str, object]:
                    return {"symbol": "ETH", "balance_wei": "0", "balance": "0"}

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").lookup_address("friend", "mainnet")
            self.assertEqual(payload["query_kind"], "address_book")
            self.assertEqual(payload["classification"], "contract")
            self.assertEqual(FakeClient.last_address, "0x2222222222222222222222222222222222222222")

    def test_lookup_contract_reports_contract_details_and_proxy_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)

            class FakeClient:
                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def inspect_contract(self, address: str) -> dict[str, object]:
                    return {
                        "address": address,
                        "classification": "contract",
                        "nonce": 8,
                        "code_present": True,
                        "code_size_bytes": 2048,
                        "detected_interfaces": ["erc165", "erc721"],
                        "proxy_hints": {
                            "implementation": "0x4444444444444444444444444444444444444444",
                            "admin": "0x5555555555555555555555555555555555555555",
                            "beacon": None,
                            "is_proxy": True,
                        },
                        "token_hints": {
                            "token_standard": "erc721",
                            "name": "Collectible",
                            "symbol": "NFT",
                            "decimals": None,
                            "total_supply": "12",
                            "metadata_uri": None,
                        },
                    }

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").lookup_contract("friend", "mainnet")
            self.assertEqual(payload["classification"], "contract")
            self.assertEqual(payload["code_size_bytes"], 2048)
            self.assertEqual(payload["token_standard"], "erc721")
            self.assertTrue(payload["proxy_hints"]["is_proxy"])
            self.assertEqual(payload["proxy_hints"]["implementation"], "0x4444444444444444444444444444444444444444")

    def test_lookup_token_detects_erc20_and_holder_balance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)

            class FakeClient:
                last_holder: str | None = None

                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def inspect_token(self, address: str, holder: str | None = None) -> dict[str, object]:
                    FakeClient.last_holder = holder
                    return {
                        "address": address,
                        "token_standard": "erc20",
                        "name": "USD Coin",
                        "symbol": "USDC",
                        "decimals": 6,
                        "total_supply": "1000000",
                        "metadata_uri": None,
                        "is_contract": True,
                        "code_size_bytes": 1024,
                        "detected_interfaces": ["erc20"],
                        "proxy_hints": {"implementation": None, "admin": None, "beacon": None, "is_proxy": False},
                        "holder": {
                            "address": holder,
                            "balance_lookup_supported": True,
                            "balance_raw": "2500000",
                            "balance": "2.5",
                            "note": None,
                        },
                    }

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").lookup_token("friend", "mainnet", holder="main")
            self.assertEqual(payload["token_standard"], "erc20")
            self.assertEqual(payload["holder"]["query_kind"], "account")
            self.assertEqual(payload["holder"]["balance"], "2.5")
            self.assertEqual(FakeClient.last_holder, "0x1111111111111111111111111111111111111111")

    def test_lookup_token_supports_erc721_and_erc1155_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)

            class FakeClient:
                mode = "erc721"

                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def inspect_token(self, address: str, holder: str | None = None) -> dict[str, object]:
                    if self.mode == "erc721":
                        return {
                            "address": address,
                            "token_standard": "erc721",
                            "name": "Collectible",
                            "symbol": "NFT",
                            "decimals": None,
                            "total_supply": "12",
                            "metadata_uri": None,
                            "is_contract": True,
                            "code_size_bytes": 900,
                            "detected_interfaces": ["erc165", "erc721"],
                            "proxy_hints": {"implementation": None, "admin": None, "beacon": None, "is_proxy": False},
                        }
                    return {
                        "address": address,
                        "token_standard": "erc1155",
                        "name": None,
                        "symbol": None,
                        "decimals": None,
                        "total_supply": None,
                        "metadata_uri": "ipfs://{id}.json",
                        "is_contract": True,
                        "code_size_bytes": 901,
                        "detected_interfaces": ["erc165", "erc1155", "erc1155_metadata_uri"],
                        "proxy_hints": {"implementation": None, "admin": None, "beacon": None, "is_proxy": False},
                    }

            with patch("vault.service.EVMClient", FakeClient):
                service = VaultService(home=temp_dir, profile="prod")
                erc721_payload = service.lookup_token("friend", "mainnet")
                FakeClient.mode = "erc1155"
                erc1155_payload = service.lookup_token("friend", "mainnet")
            self.assertEqual(erc721_payload["token_standard"], "erc721")
            self.assertEqual(erc721_payload["symbol"], "NFT")
            self.assertEqual(erc1155_payload["token_standard"], "erc1155")
            self.assertEqual(erc1155_payload["metadata_uri"], "ipfs://{id}.json")

    def test_lookup_token_unknown_contract_returns_successful_unknown_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)

            class FakeClient:
                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def inspect_token(self, address: str, holder: str | None = None) -> dict[str, object]:
                    return {
                        "address": address,
                        "token_standard": "unknown",
                        "name": None,
                        "symbol": None,
                        "decimals": None,
                        "total_supply": None,
                        "metadata_uri": None,
                        "is_contract": True,
                        "code_size_bytes": 77,
                        "detected_interfaces": [],
                        "proxy_hints": {"implementation": None, "admin": None, "beacon": None, "is_proxy": False},
                    }

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").lookup_token("friend", "mainnet")
            self.assertEqual(payload["token_standard"], "unknown")
            self.assertTrue(payload["is_contract"])

    def test_lookup_uses_default_network_when_network_argument_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)

            class FakeClient:
                last_network_name: str | None = None

                def __init__(self, network: dict[str, object]) -> None:
                    FakeClient.last_network_name = str(network["name"])

                def inspect_address(self, address: str) -> dict[str, object]:
                    return {
                        "address": address,
                        "classification": "eoa",
                        "nonce": 0,
                        "code_present": False,
                        "code_size_bytes": 0,
                        "detected_interfaces": [],
                        "proxy_hints": {"implementation": None, "admin": None, "beacon": None, "is_proxy": False},
                    }

                def get_native_balance(self, address: str) -> dict[str, object]:
                    return {"symbol": "ETH", "balance_wei": "0", "balance": "0"}

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").lookup_address("main")
            self.assertEqual(payload["network"], "mainnet")
            self.assertEqual(FakeClient.last_network_name, "mainnet")

    def test_contract_read_resolves_address_book_and_returns_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)
            abi_path = Path(temp_dir) / "reader.json"
            save_json(
                abi_path,
                [
                    {
                        "name": "value",
                        "type": "function",
                        "inputs": [],
                        "outputs": [{"type": "uint256"}],
                    }
                ],
            )

            class FakeClient:
                last_abi: list[dict[str, object]] | None = None

                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def get_contract_read(
                    self,
                    address: str,
                    abi: list[dict[str, object]],
                    function_name: str,
                    args: list[object] | None = None,
                ) -> dict[str, object]:
                    FakeClient.last_abi = abi
                    return {
                        "address": address,
                        "call_succeeded": True,
                        "result": 7,
                        "result_type_hint": "uint256",
                        "code_present": True,
                        "code_size_bytes": 123,
                        "error": None,
                    }

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").contract_read(
                    target="friend",
                    function_name="value",
                    abi_file=str(abi_path),
                    network_name="mainnet",
                )
            self.assertEqual(payload["query_kind"], "address_book")
            self.assertEqual(payload["result"], 7)
            self.assertEqual(payload["abi_source"], "file")
            self.assertEqual(FakeClient.last_abi[0]["name"], "value")

    def test_contract_write_preview_builds_generic_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)

            class FakeClient:
                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def prepare_contract_write(self, **kwargs: object) -> dict[str, object]:
                    self.kwargs = kwargs
                    return {
                        "summary": "Prepared contract write on mainnet",
                        "network": "mainnet",
                        "chain_id": 1,
                        "asset_type": "contract",
                        "from_address": "0x1111111111111111111111111111111111111111",
                        "to_address": "0x2222222222222222222222222222222222222222",
                        "contract_function": "setValue",
                        "args": [1],
                        "value": "0.5",
                        "value_wei": "500000000000000000",
                        "data": "0x1234",
                        "nonce": 3,
                        "gas_limit": 70000,
                        "fee_model": "eip1559",
                        "max_fee_cost_wei": "10",
                        "estimated_total_cost_wei": "500000000000000010",
                        "tx": {"nonce": 3},
                    }

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").preview_contract_write(
                    from_account_name="main",
                    target="friend",
                    function_name="setValue",
                    abi_fragment='{"name":"setValue","type":"function","inputs":[{"type":"uint256"}],"outputs":[]}',
                    args_json="[1]",
                    value="0.5",
                    network_name="mainnet",
                )
            self.assertEqual(payload["asset_type"], "contract")
            self.assertEqual(payload["action"], "contract_write")
            self.assertEqual(payload["query_kind"], "address_book")
            self.assertEqual(payload["value"], "0.5")
            self.assertIn("Action allowed by policy.", payload["policy_findings"])

    def test_contract_write_execute_records_submitted_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = VaultService(home=temp_dir, profile="prod")

            class FakeNetworks:
                def get_network(self, name: str | None) -> dict[str, object]:
                    return {"name": name or "mainnet", "chain_id": 1, "symbol": "ETH"}

            class FakeSigner:
                can_sign = True
                signer_type = "local"

                def send_prepared(self, passphrase: str, preview: dict[str, object], network: dict[str, object]) -> dict[str, object]:
                    payload = dict(preview)
                    payload["network"] = network["name"]
                    payload["transaction_hash"] = normalize_tx_hash("aa" * 32)
                    payload.pop("tx", None)
                    return payload

            preview = {
                "profile": "prod",
                "account_name": "main",
                "account_kind": "local",
                "signer_type": "local",
                "can_sign": True,
                "network_name": "mainnet",
                "recipient_name": "friend",
                "requires_strong_confirmation": False,
                "requires_simulation": False,
                "asset_type": "contract",
                "action": "contract_write",
                "details": {"kind": "contract_write", "contract_function": "setValue"},
                "from_address": "0x1111111111111111111111111111111111111111",
                "to_address": "0x2222222222222222222222222222222222222222",
                "contract_function": "setValue",
                "args": [1],
                "value": "0",
                "value_wei": "0",
                "nonce": 1,
                "gas_limit": 21000,
                "fee_model": "eip1559",
                "max_fee_cost_wei": "1",
                "estimated_total_cost_wei": "1",
                "tx": {"nonce": 1},
            }

            with patch.object(service, "_networks", return_value=FakeNetworks()):
                with patch("vault.service.resolve_signer", return_value=FakeSigner()):
                    payload = service.execute_contract_write(passphrase="secret", preview=preview)
            self.assertEqual(payload["transaction_hash"], normalize_tx_hash("aa" * 32))
            entry = service.show_journal_entry(payload["transaction_hash"])
            self.assertEqual(entry["action"], "contract_write")
            self.assertEqual(entry["details"]["contract_function"], "setValue")

    def test_token_allowance_returns_normalized_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)
            AddressBookManager(resolve_paths(temp_dir, "prod")).add_entry(
                "router",
                "0x3333333333333333333333333333333333333333",
                network_scope="mainnet",
            )

            class FakeClient:
                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def get_token_allowance(self, token_address: str, owner: str, spender: str) -> dict[str, object]:
                    return {
                        "token_address": token_address,
                        "owner_address": owner,
                        "spender_address": spender,
                        "symbol": "USDC",
                        "decimals": 6,
                        "allowance_raw": "1200000",
                        "allowance": "1.2",
                    }

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").token_allowance(
                    token_target="friend",
                    owner="main",
                    spender="router",
                    network_name="mainnet",
                )
            self.assertEqual(payload["token_query_kind"], "address_book")
            self.assertEqual(payload["owner_query_kind"], "account")
            self.assertEqual(payload["spender_query_kind"], "address_book")
            self.assertEqual(payload["allowance"], "1.2")

    def test_token_approve_preview_returns_token_specific_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)
            AddressBookManager(resolve_paths(temp_dir, "prod")).add_entry(
                "router",
                "0x3333333333333333333333333333333333333333",
                network_scope="mainnet",
            )

            class FakeClient:
                def __init__(self, network: dict[str, object]) -> None:
                    self.network = network

                def prepare_token_approve(self, **kwargs: object) -> dict[str, object]:
                    return {
                        "summary": "Prepared ERC-20 approval on mainnet",
                        "network": "mainnet",
                        "chain_id": 1,
                        "asset_type": "erc20_approval",
                        "from_address": "0x1111111111111111111111111111111111111111",
                        "to_address": "0x2222222222222222222222222222222222222222",
                        "contract_function": "approve",
                        "args": ["0x3333333333333333333333333333333333333333", 1],
                        "value": "0",
                        "value_wei": "0",
                        "data": "0x1234",
                        "nonce": 1,
                        "gas_limit": 60000,
                        "fee_model": "eip1559",
                        "max_fee_cost_wei": "1",
                        "estimated_total_cost_wei": "1",
                        "token_address": "0x2222222222222222222222222222222222222222",
                        "spender_address": "0x3333333333333333333333333333333333333333",
                        "symbol": "USDC",
                        "decimals": 6,
                        "amount": "1",
                        "amount_raw": "1000000",
                        "tx": {"nonce": 1},
                    }

            with patch("vault.service.EVMClient", FakeClient):
                payload = VaultService(home=temp_dir, profile="prod").preview_token_approve(
                    from_account_name="main",
                    token_target="friend",
                    spender="router",
                    amount="1",
                    network_name="mainnet",
                )
            self.assertEqual(payload["asset_type"], "erc20_approval")
            self.assertEqual(payload["action"], "token_approve")
            self.assertEqual(payload["spender_query_kind"], "address_book")
            self.assertEqual(payload["amount_raw"], "1000000")

    def test_contract_abi_source_validation_requires_exactly_one_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.seed_lookup_store(temp_dir)
            service = VaultService(home=temp_dir, profile="prod")
            with self.assertRaises(VaultError):
                service.contract_read(target="friend", function_name="value", network_name="mainnet")

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
                    payload["transaction_hash"] = normalize_tx_hash("ab" * 32)
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
            self.assertEqual(payload["transaction_hash"], normalize_tx_hash("ab" * 32))
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
            NetworkManager(resolve_paths(temp_dir, "prod")).add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)
            service = VaultService(home=temp_dir, profile="prod")
            service.set_policy_rule("blocked_networks", "mainnet")
            with self.assertRaises(VaultError):
                service.preview_send("main", "mainnet", "0x2222222222222222222222222222222222222222", "0.5")

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
            NetworkManager(resolve_paths(temp_dir, "prod")).add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)

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
                preview = VaultService(home=temp_dir, profile="prod").preview_send("main", "mainnet", "0x2222222222222222222222222222222222222222", "0.5")
            self.assertTrue(preview["requires_strong_confirmation"])

    def test_separate_dev_dry_run_returns_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = VaultService(home=temp_dir).separate_dev("main", "mainnet", "local-dev", "local", dry_run=True)
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
            manager = NetworkManager(prod_paths)
            manager.add_network("mainnet", "https://rpc.example", 1, "ETH")
            manager.add_anvil_network(name="local", set_default=True)
            payload = VaultService(home=temp_dir, profile="prod").separate_dev("main", "mainnet", "local-dev", "local")
            self.assertEqual(payload["dev_default_account"], "local-dev")
            dev_accounts = VaultService(home=temp_dir, profile="dev").list_accounts()
            self.assertEqual(dev_accounts["default_account"], "local-dev")

    def test_safety_status_warns_when_home_is_inside_git_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            (repo_root / ".git").mkdir(parents=True)
            home = repo_root / ".vault-test"
            payload = VaultService(home=str(home), profile="prod").safety_status()
            self.assertIn("inside a git worktree", " ".join(payload["findings"]))


class StorageHardeningTests(unittest.TestCase):
    def test_save_json_writes_private_file_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "secret.json"
            save_json(path, {"ok": True})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_save_json_writes_private_directory_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vault" / "state.json"
            save_json(path, {"ok": True})
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)


class MonitorServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        temp_path = Path(self.temp_dir.name)
        save_json(
            temp_path / "accounts" / "main.json",
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
        save_json(
            temp_path / "accounts" / "watcher.json",
            {
                "version": 1,
                "name": "watcher",
                "address": "0x3333333333333333333333333333333333333333",
                "source": "watch_only",
                "account_kind": "watch_only",
                "signer_type": "watch_only",
                "can_sign": False,
            },
        )
        save_json(temp_path / "config.json", {"default_account": "main"})
        NetworkManager(resolve_paths(self.temp_dir.name, "prod")).add_network("mainnet", "https://rpc.example", 1, "ETH", set_default=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def service(self) -> VaultService:
        return VaultService(home=self.temp_dir.name, profile="prod")

    def test_first_run_initializes_monitor_state(self) -> None:
        class FakeClient:
            latest_block = 10
            balance_wei = "1000000000000000000"
            nonce = 1

            def __init__(self, network: dict[str, object]) -> None:
                self.network = network

            def get_latest_block_number(self) -> int:
                return self.latest_block

            def get_native_balance(self, address: str) -> dict[str, object]:
                return {
                    "summary": "Balance",
                    "network": "mainnet",
                    "chain_id": 1,
                    "address": address,
                    "asset_type": "native",
                    "symbol": "ETH",
                    "balance_wei": self.balance_wei,
                    "balance": "1",
                }

            def get_transaction_count(self, address: str) -> int:
                return self.nonce

            def get_relevant_transactions(self, address: str, start_block: int, end_block: int) -> list[dict[str, object]]:
                return []

            def get_transaction_receipt_or_none(self, tx_hash: str) -> dict[str, object] | None:
                return None

        with patch("vault.service.EVMClient", FakeClient):
            payload = self.service().monitor_poll("main", "mainnet")
        self.assertEqual(payload["new_event_count"], 0)
        self.assertEqual(payload["state"]["last_processed_block"], 10)
        self.assertEqual(payload["state"]["last_known_nonce"], 1)

    def test_no_op_poll_when_nothing_changed(self) -> None:
        class FakeClient:
            latest_block = 10
            balance_wei = "1000000000000000000"

            def __init__(self, network: dict[str, object]) -> None:
                self.network = network

            def get_latest_block_number(self) -> int:
                return self.latest_block

            def get_native_balance(self, address: str) -> dict[str, object]:
                return {
                    "summary": "Balance",
                    "network": "mainnet",
                    "chain_id": 1,
                    "address": address,
                    "asset_type": "native",
                    "symbol": "ETH",
                    "balance_wei": self.balance_wei,
                    "balance": "1",
                }

            def get_transaction_count(self, address: str) -> int:
                return 0

            def get_relevant_transactions(self, address: str, start_block: int, end_block: int) -> list[dict[str, object]]:
                return []

            def get_transaction_receipt_or_none(self, tx_hash: str) -> dict[str, object] | None:
                return None

        with patch("vault.service.EVMClient", FakeClient):
            service = self.service()
            service.monitor_poll("main", "mainnet")
            payload = service.monitor_poll("main", "mainnet")
        self.assertEqual(payload["new_event_count"], 0)

    def test_outgoing_transaction_detection(self) -> None:
        tx_hash = normalize_tx_hash("ab" * 32)

        class FakeClient:
            latest_block = 10
            balance_wei = "1000000000000000000"
            receipts = {tx_hash: {"transaction_hash": tx_hash, "network": "mainnet", "chain_id": 1, "block_number": 11, "status": 1, "gas_used": 21000, "effective_gas_price": "1"}}
            txs: list[dict[str, object]] = []

            def __init__(self, network: dict[str, object]) -> None:
                self.network = network

            def get_latest_block_number(self) -> int:
                return self.latest_block

            def get_native_balance(self, address: str) -> dict[str, object]:
                return {
                    "summary": "Balance",
                    "network": "mainnet",
                    "chain_id": 1,
                    "address": address,
                    "asset_type": "native",
                    "symbol": "ETH",
                    "balance_wei": self.balance_wei,
                    "balance": "1",
                }

            def get_transaction_count(self, address: str) -> int:
                return 1

            def get_relevant_transactions(self, address: str, start_block: int, end_block: int) -> list[dict[str, object]]:
                return list(self.txs)

            def get_transaction_receipt_or_none(self, tx_hash_arg: str) -> dict[str, object] | None:
                return self.receipts.get(tx_hash_arg)

        with patch("vault.service.EVMClient", FakeClient):
            service = self.service()
            service.monitor_poll("main", "mainnet")
            FakeClient.latest_block = 11
            FakeClient.txs = [
                {
                    "transaction_hash": tx_hash,
                    "network": "mainnet",
                    "chain_id": 1,
                    "block_number": 11,
                    "from_address": "0x1111111111111111111111111111111111111111",
                    "to_address": "0x2222222222222222222222222222222222222222",
                    "value_wei": "100000000000000000",
                    "nonce": 1,
                }
            ]
            payload = service.monitor_poll("main", "mainnet")
        event_types = {row["event_type"] for row in payload["new_events"]}
        self.assertIn("outgoing_transaction_observed", event_types)
        self.assertIn("transaction_confirmed", event_types)

    def test_incoming_transaction_detection(self) -> None:
        tx_hash = normalize_tx_hash("cd" * 32)

        class FakeClient:
            latest_block = 3
            receipts = {tx_hash: {"transaction_hash": tx_hash, "network": "mainnet", "chain_id": 1, "block_number": 4, "status": 1, "gas_used": 21000, "effective_gas_price": "1"}}
            txs: list[dict[str, object]] = []

            def __init__(self, network: dict[str, object]) -> None:
                self.network = network

            def get_latest_block_number(self) -> int:
                return self.latest_block

            def get_native_balance(self, address: str) -> dict[str, object]:
                return {
                    "summary": "Balance",
                    "network": "mainnet",
                    "chain_id": 1,
                    "address": address,
                    "asset_type": "native",
                    "symbol": "ETH",
                    "balance_wei": "1000000000000000000",
                    "balance": "1",
                }

            def get_transaction_count(self, address: str) -> int:
                return 0

            def get_relevant_transactions(self, address: str, start_block: int, end_block: int) -> list[dict[str, object]]:
                return list(self.txs)

            def get_transaction_receipt_or_none(self, tx_hash_arg: str) -> dict[str, object] | None:
                return self.receipts.get(tx_hash_arg)

        with patch("vault.service.EVMClient", FakeClient):
            service = self.service()
            service.monitor_poll("main", "mainnet")
            FakeClient.latest_block = 4
            FakeClient.txs = [
                {
                    "transaction_hash": tx_hash,
                    "network": "mainnet",
                    "chain_id": 1,
                    "block_number": 4,
                    "from_address": "0x2222222222222222222222222222222222222222",
                    "to_address": "0x1111111111111111111111111111111111111111",
                    "value_wei": "100000000000000000",
                    "nonce": 5,
                }
            ]
            payload = service.monitor_poll("main", "mainnet")
        event_types = {row["event_type"] for row in payload["new_events"]}
        self.assertIn("incoming_transaction_observed", event_types)

    def test_receipt_transition_from_pending_to_confirmed(self) -> None:
        tx_hash = normalize_tx_hash("ef" * 32)
        journal = JournalManager(resolve_paths(self.temp_dir.name, "prod"))
        journal.record_submitted_transaction(
            {
                "transaction_hash": tx_hash,
                "profile": "prod",
                "network": "mainnet",
                "chain_id": 1,
                "account_name": "main",
                "from_address": "0x1111111111111111111111111111111111111111",
                "to_address": "0x2222222222222222222222222222222222222222",
                "symbol": "ETH",
                "asset_type": "native",
                "amount": "1",
                "amount_wei": "1000000000000000000",
                "nonce": 1,
                "gas_limit": 21000,
                "fee_model": "eip1559",
                "max_fee_cost_wei": "1",
                "estimated_total_cost_wei": "1",
                "submitted_at": "2026-04-21T00:00:00+00:00",
            }
        )

        class FakeClient:
            def __init__(self, network: dict[str, object]) -> None:
                self.network = network

            def get_latest_block_number(self) -> int:
                return 1

            def get_native_balance(self, address: str) -> dict[str, object]:
                return {
                    "summary": "Balance",
                    "network": "mainnet",
                    "chain_id": 1,
                    "address": address,
                    "asset_type": "native",
                    "symbol": "ETH",
                    "balance_wei": "1000000000000000000",
                    "balance": "1",
                }

            def get_transaction_count(self, address: str) -> int:
                return 1

            def get_relevant_transactions(self, address: str, start_block: int, end_block: int) -> list[dict[str, object]]:
                return []

            def get_transaction_receipt_or_none(self, tx_hash_arg: str) -> dict[str, object] | None:
                if tx_hash_arg == tx_hash:
                    return {
                        "transaction_hash": tx_hash,
                        "network": "mainnet",
                        "chain_id": 1,
                        "block_number": 2,
                        "status": 1,
                        "gas_used": 21000,
                        "effective_gas_price": "1",
                    }
                return None

        with patch("vault.service.EVMClient", FakeClient):
            payload = self.service().monitor_poll("main", "mainnet")
        self.assertEqual(payload["new_event_count"], 1)
        updated = journal.get_entry(tx_hash)
        self.assertEqual(updated["status"], "confirmed")

    def test_native_balance_delta_detection(self) -> None:
        class FakeClient:
            latest_block = 1
            balance_wei = "1000000000000000000"

            def __init__(self, network: dict[str, object]) -> None:
                self.network = network

            def get_latest_block_number(self) -> int:
                return self.latest_block

            def get_native_balance(self, address: str) -> dict[str, object]:
                balance = "1" if self.balance_wei == "1000000000000000000" else "1.5"
                return {
                    "summary": "Balance",
                    "network": "mainnet",
                    "chain_id": 1,
                    "address": address,
                    "asset_type": "native",
                    "symbol": "ETH",
                    "balance_wei": self.balance_wei,
                    "balance": balance,
                }

            def get_transaction_count(self, address: str) -> int:
                return 0

            def get_relevant_transactions(self, address: str, start_block: int, end_block: int) -> list[dict[str, object]]:
                return []

            def get_transaction_receipt_or_none(self, tx_hash_arg: str) -> dict[str, object] | None:
                return None

        with patch("vault.service.EVMClient", FakeClient):
            service = self.service()
            service.monitor_poll("main", "mainnet")
            FakeClient.balance_wei = "1500000000000000000"
            payload = service.monitor_poll("main", "mainnet")
        self.assertEqual(payload["new_event_count"], 1)
        self.assertEqual(payload["new_events"][0]["event_type"], "native_balance_changed")

    def test_watch_only_account_monitoring(self) -> None:
        class FakeClient:
            def __init__(self, network: dict[str, object]) -> None:
                self.network = network

            def get_latest_block_number(self) -> int:
                return 5

            def get_native_balance(self, address: str) -> dict[str, object]:
                return {
                    "summary": "Balance",
                    "network": "mainnet",
                    "chain_id": 1,
                    "address": address,
                    "asset_type": "native",
                    "symbol": "ETH",
                    "balance_wei": "0",
                    "balance": "0",
                }

            def get_transaction_count(self, address: str) -> int:
                return 0

            def get_relevant_transactions(self, address: str, start_block: int, end_block: int) -> list[dict[str, object]]:
                return []

            def get_transaction_receipt_or_none(self, tx_hash_arg: str) -> dict[str, object] | None:
                return None

        with patch("vault.service.EVMClient", FakeClient):
            payload = self.service().monitor_poll("watcher", "mainnet")
        self.assertEqual(payload["account_name"], "watcher")
        self.assertEqual(payload["new_event_count"], 0)

    def test_missing_default_arguments_resolve_from_defaults(self) -> None:
        class FakeClient:
            def __init__(self, network: dict[str, object]) -> None:
                self.network = network

            def get_latest_block_number(self) -> int:
                return 7

            def get_native_balance(self, address: str) -> dict[str, object]:
                return {
                    "summary": "Balance",
                    "network": "mainnet",
                    "chain_id": 1,
                    "address": address,
                    "asset_type": "native",
                    "symbol": "ETH",
                    "balance_wei": "1",
                    "balance": "0.000000000000000001",
                }

            def get_transaction_count(self, address: str) -> int:
                return 0

            def get_relevant_transactions(self, address: str, start_block: int, end_block: int) -> list[dict[str, object]]:
                return []

            def get_transaction_receipt_or_none(self, tx_hash_arg: str) -> dict[str, object] | None:
                return None

        with patch("vault.service.EVMClient", FakeClient):
            payload = self.service().monitor_poll()
        self.assertEqual(payload["account_name"], "main")
        self.assertEqual(payload["network"], "mainnet")


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
                "accounts": [{"name": "alice", "address": "0x1111111111111111111111111111111111111111", "is_default": True}],
            }
        )
        self.assertIn("Accounts:\n- ", rendered)
        self.assertIn("name=alice", rendered)

    def test_redact_rpc_url_masks_api_key_segment(self) -> None:
        rendered = redact_rpc_url("https://eth-sepolia.g.alchemy.com/v2/secret-api-key")
        self.assertEqual(rendered, "https://eth-sepolia.g.alchemy.com/v2/***")

    def test_redact_rpc_url_masks_userinfo_and_secret_query_values(self) -> None:
        rendered = redact_rpc_url("https://user:pass@rpc.example/v1/key?token=secret&foo=bar")
        self.assertEqual(rendered, "https://rpc.example/v1/key?token=%2A%2A%2A&foo=bar")


class JournalTests(unittest.TestCase):
    def test_normalize_tx_hash_accepts_bare_hex(self) -> None:
        bare = "ab" * 32
        self.assertEqual(normalize_tx_hash(bare), f"0x{bare}")

    def test_non_transaction_event_identifier_is_preserved(self) -> None:
        entry_id = normalize_event_id("monitor:main:local:event")
        self.assertEqual(entry_id, "monitor:main:local:event")

    def test_mixed_event_ordering_and_receipt_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = JournalManager(resolve_paths(temp_dir))
            manager.record_event(
                "monitor:older",
                "monitor_transaction_observed",
                {
                    "origin": "monitor",
                    "kind": "observation",
                    "event_type": "incoming_transaction_observed",
                    "status": "observed",
                    "created_at": "2026-04-21T00:00:00+00:00",
                },
            )
            tx_hash = normalize_tx_hash("cd" * 32)
            manager.record_submitted_transaction(
                {
                    "transaction_hash": tx_hash,
                    "profile": "dev",
                    "network": "local",
                    "chain_id": 31337,
                    "account_name": "local-dev",
                    "from_address": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266",
                    "to_address": "0x1111111111111111111111111111111111111111",
                    "symbol": "ETH",
                    "asset_type": "native",
                    "amount": "1",
                    "amount_wei": "1",
                    "nonce": 1,
                    "gas_limit": 21000,
                    "fee_model": "eip1559",
                    "max_fee_cost_wei": "1",
                    "estimated_total_cost_wei": "2",
                    "submitted_at": "2026-04-21T01:00:00+00:00",
                }
            )
            rows = manager.list_entries()["entries"]
            self.assertEqual(rows[0]["id"], tx_hash)
            attached = manager.attach_receipt(
                tx_hash,
                {
                    "transaction_hash": tx_hash,
                    "network": "local",
                    "chain_id": 31337,
                    "block_number": 2,
                    "status": 1,
                    "gas_used": 21000,
                    "effective_gas_price": "1",
                },
            )
            self.assertEqual(attached["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
