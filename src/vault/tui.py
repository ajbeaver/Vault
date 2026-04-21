from __future__ import annotations

import json
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from vault.config import VaultError
from vault.service import VaultService
from vault.themes import cycle_theme_name, resolve_textual_theme


class EntityListItem(ListItem):
    def __init__(self, entity_name: str, title: str, subtitle: str = "") -> None:
        self.entity_name = entity_name
        body = f"[b]{title}[/b]"
        if subtitle:
            body += f"\n{subtitle}"
        super().__init__(Label(body))


class VaultTUI(App[None]):
    CSS = """
    Screen {
      layout: vertical;
      background: $surface;
    }

    #top {
      height: 1fr;
    }

    #sidebar {
      width: 36;
      min-width: 30;
      padding: 1;
      overflow-x: auto;
      overflow-y: auto;
      border: round $accent;
      background: $panel;
    }

    #main {
      width: 1fr;
      padding: 1;
      overflow-x: auto;
      overflow-y: auto;
    }

    #context_bar {
      height: auto;
      min-height: 5;
      margin-bottom: 1;
      padding: 1;
      border: round $accent;
      background: $panel;
    }

    .status-card {
      height: auto;
      min-height: 5;
      margin-bottom: 1;
      padding: 1;
      border: round $surface-lighten-1;
      background: $boost;
    }

    .quick-row {
      height: auto;
      margin-top: 1;
      overflow-x: auto;
    }

    .quick-row Button {
      width: auto;
      min-width: 10;
      margin-right: 1;
    }

    .quick-row Button:last-child {
      margin-right: 0;
    }

    .master-detail {
      height: 1fr;
    }

    .list-column {
      width: 34;
      min-width: 30;
      margin-right: 1;
      padding: 1;
      overflow-y: auto;
      border: round $surface-lighten-1;
      background: $boost;
    }

    .detail-column {
      width: 1fr;
      padding: 1;
      overflow-y: auto;
      border: round $surface-lighten-1;
      background: $boost;
    }

    .section-title {
      text-style: bold;
      margin-bottom: 1;
    }

    .detail-panel,
    .preview-panel,
    .result-panel,
    .balance-panel {
      height: auto;
      min-height: 10;
      margin-bottom: 1;
      padding: 1;
      border: round $accent;
      background: $panel;
    }

    .form-block {
      height: auto;
      margin-top: 1;
      padding-top: 1;
      border-top: tall $surface-lighten-1;
    }

    .form-actions {
      height: auto;
      margin-top: 1;
      overflow-x: auto;
    }

    .form-actions Button {
      width: auto;
      min-width: 14;
      margin-right: 1;
    }

    .send-layout {
      height: 1fr;
    }

    .send-form-column {
      width: 42;
      min-width: 36;
      margin-right: 1;
      padding: 1;
      overflow-y: auto;
      border: round $surface-lighten-1;
      background: $boost;
    }

    .send-preview-column {
      width: 1fr;
      padding: 1;
      overflow-y: auto;
      border: round $surface-lighten-1;
      background: $boost;
    }

    ListView {
      height: 1fr;
      margin-top: 1;
      border: round $surface;
      background: $panel;
    }

    RichLog {
      height: 10;
      border: round $accent;
      background: $panel;
    }

    Input {
      margin-bottom: 1;
    }

    TabbedContent {
      height: 1fr;
    }

    TabbedContent > Tabs {
      width: 1fr;
      overflow-x: scroll;
      overflow-y: hidden;
    }

    TabPane {
      height: 1fr;
      overflow-y: auto;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_all", "Refresh"),
        ("b", "refresh_balance", "Balance"),
        ("1", "show_profiles", "Profiles"),
        ("2", "show_accounts", "Accounts"),
        ("3", "show_networks", "Networks"),
        ("4", "show_address_book", "Address Book"),
        ("5", "show_balance", "Balance"),
        ("6", "show_lookup", "Lookup"),
        ("c", "show_contracts", "Contracts"),
        ("7", "show_send", "Send"),
        ("8", "show_monitor", "Monitor"),
        ("9", "show_policy", "Policy"),
        ("0", "show_journal", "Journal"),
        ("d", "switch_to_dev", "Dev"),
        ("t", "switch_to_test", "Test"),
        ("p", "switch_to_prod", "Prod"),
        ("[", "theme_previous", "Prev Theme"),
        ("]", "theme_next", "Next Theme"),
    ]

    def __init__(self, home: str | None = None, profile: str | None = None, allow_prod: bool = False) -> None:
        super().__init__()
        self.service = VaultService(home=home, profile=profile)
        self.allow_prod = allow_prod
        self.current_theme_name = self.service.show_theme()["name"]
        self._last_log_message: str | None = None
        self.last_preview: dict[str, Any] | None = None
        self.last_contract_preview: dict[str, Any] | None = None
        self.last_balance_snapshot: dict[str, Any] | None = None
        self.last_lookup_result: dict[str, Any] | None = None
        self.monitor_timer: Timer | None = None
        self.monitor_recent_events: list[dict[str, Any]] = []
        self.monitor_last_payload: dict[str, Any] | None = None
        self.profile_rows: list[dict[str, Any]] = []
        self.account_rows: list[dict[str, Any]] = []
        self.network_rows: list[dict[str, Any]] = []
        self.book_rows: list[dict[str, Any]] = []
        self.journal_rows: list[dict[str, Any]] = []
        self.selected_profile_name: str | None = None
        self.selected_account_name: str | None = None
        self.selected_network_name: str | None = None
        self.selected_book_name: str | None = None
        self.selected_journal_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            with VerticalScroll(id="sidebar"):
                yield Static("", id="status_profile", classes="status-card")
                yield Static("", id="status_account", classes="status-card")
                yield Static("", id="status_network", classes="status-card")
                yield Static("", id="status_balance", classes="status-card")
                yield Static("", id="status_safety", classes="status-card")
                with HorizontalScroll(classes="quick-row"):
                    yield Button("Refresh", id="refresh_button", variant="primary")
                    yield Button("Reload Bal", id="refresh_balance_button")
                with HorizontalScroll(classes="quick-row"):
                    yield Button("Dev", id="profile_dev")
                    yield Button("Test", id="profile_test")
                    yield Button("Prod", id="profile_prod")
                with HorizontalScroll(classes="quick-row"):
                    yield Button("Theme -", id="theme_prev_button")
                    yield Button("Theme +", id="theme_next_button")
            with VerticalScroll(id="main"):
                yield Static("", id="context_bar")
                with TabbedContent(id="tabs"):
                    with TabPane("Profiles", id="tab_profiles"):
                        with Horizontal(classes="master-detail"):
                            with Vertical(classes="list-column"):
                                yield Label("Profiles", classes="section-title")
                                yield ListView(id="profiles_list")
                            with VerticalScroll(classes="detail-column"):
                                yield Label("Profile Detail", classes="section-title")
                                yield Static("", id="profiles_detail", classes="detail-panel")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Activate Selected", id="profiles_activate_button", variant="primary")

                    with TabPane("Accounts", id="tab_accounts"):
                        with Horizontal(classes="master-detail"):
                            with Vertical(classes="list-column"):
                                yield Label("Accounts", classes="section-title")
                                yield ListView(id="accounts_list")
                            with VerticalScroll(classes="detail-column"):
                                yield Label("Account Detail", classes="section-title")
                                yield Static("", id="accounts_detail", classes="detail-panel")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Set Default", id="account_set_default_button", variant="primary")
                                    yield Button("Use In Forms", id="account_use_forms_button")
                                with Vertical(classes="form-block"):
                                    yield Label("Create account", classes="section-title")
                                    yield Input(placeholder="Name", id="account_create_name")
                                    yield Input(password=True, placeholder="Passphrase", id="account_create_passphrase")
                                    yield Input(password=True, placeholder="Confirm passphrase", id="account_create_passphrase_confirm")
                                    yield Button("Create Account", id="account_create_button")
                                with Vertical(classes="form-block"):
                                    yield Label("Import account", classes="section-title")
                                    yield Input(placeholder="Name", id="account_import_name")
                                    yield Input(password=True, placeholder="Private key (hex)", id="account_import_private_key")
                                    yield Input(password=True, placeholder="Passphrase", id="account_import_passphrase")
                                    yield Input(password=True, placeholder="Confirm passphrase", id="account_import_passphrase_confirm")
                                    yield Button("Import Account", id="account_import_button")
                                with Vertical(classes="form-block"):
                                    yield Label("Add watch-only", classes="section-title")
                                    yield Input(placeholder="Name", id="account_watch_name")
                                    yield Input(placeholder="Address", id="account_watch_address")
                                    yield Button("Add Watch Account", id="account_watch_button")

                    with TabPane("Networks", id="tab_networks"):
                        with Horizontal(classes="master-detail"):
                            with Vertical(classes="list-column"):
                                yield Label("Networks", classes="section-title")
                                yield ListView(id="networks_list")
                            with VerticalScroll(classes="detail-column"):
                                yield Label("Network Detail", classes="section-title")
                                yield Static("", id="networks_detail", classes="detail-panel")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Set Default", id="network_set_default_button", variant="primary")
                                    yield Button("Use In Forms", id="network_use_forms_button")
                                with Vertical(classes="form-block"):
                                    yield Label("Add Anvil network", classes="section-title")
                                    yield Input(value="local", id="network_anvil_name")
                                    yield Input(value="http://127.0.0.1:8545", id="network_anvil_rpc_url")
                                    yield Input(value="31337", id="network_anvil_chain_id")
                                    yield Input(value="ETH", id="network_anvil_symbol")
                                    yield Button("Add Anvil", id="network_anvil_button")
                                with Vertical(classes="form-block"):
                                    yield Label("Add Alchemy network", classes="section-title")
                                    yield Input(placeholder="Preset", id="network_alchemy_preset")
                                    yield Input(placeholder="Local name", id="network_alchemy_name")
                                    yield Input(value="ALCHEMY_API_KEY", id="network_alchemy_env")
                                    yield Button("Add Alchemy", id="network_alchemy_button")

                    with TabPane("Address Book", id="tab_address_book"):
                        with Horizontal(classes="master-detail"):
                            with Vertical(classes="list-column"):
                                yield Label("Address Book", classes="section-title")
                                yield ListView(id="book_list")
                            with VerticalScroll(classes="detail-column"):
                                yield Label("Recipient Detail", classes="section-title")
                                yield Static("", id="book_detail", classes="detail-panel")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Use In Send", id="book_use_selected_button", variant="primary")
                                    yield Button("Remove Selected", id="book_remove_selected_button", variant="error")
                                with Vertical(classes="form-block"):
                                    yield Label("Add entry", classes="section-title")
                                    yield Input(placeholder="Label", id="book_name")
                                    yield Input(placeholder="Address", id="book_address")
                                    yield Input(placeholder="Network scope (optional)", id="book_network")
                                    yield Input(placeholder="Notes (optional)", id="book_notes")
                                    yield Button("Add Entry", id="book_add_button")

                    with TabPane("Balance", id="tab_balance"):
                        with Horizontal(classes="send-layout"):
                            with VerticalScroll(classes="send-form-column"):
                                yield Label("Selected wallet snapshot", classes="section-title")
                                yield Input(placeholder="Account name (blank = default)", id="balance_account")
                                yield Input(placeholder="Network name (blank = default)", id="balance_network")
                                yield Input(placeholder="Token address (optional)", id="balance_token")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Fetch Balance", id="balance_button", variant="primary")
                                    yield Button("Use Defaults", id="balance_defaults_button")
                            with VerticalScroll(classes="send-preview-column"):
                                yield Label("Balance Snapshot", classes="section-title")
                                yield Static("", id="balance_snapshot_view", classes="balance-panel")

                    with TabPane("Lookup", id="tab_lookup"):
                        with Horizontal(classes="send-layout"):
                            with VerticalScroll(classes="send-form-column"):
                                yield Label("Lookup", classes="section-title")
                                yield Input(placeholder="Target address, account, or label", id="lookup_target")
                                yield Input(placeholder="Network (blank = default)", id="lookup_network")
                                yield Input(placeholder="Holder for token lookups (optional)", id="lookup_holder")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Lookup Address", id="lookup_address_button", variant="primary")
                                    yield Button("Lookup Token", id="lookup_token_button")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Lookup Contract", id="lookup_contract_button")
                                    yield Button("Load Default Net", id="lookup_defaults_button")
                            with VerticalScroll(classes="send-preview-column"):
                                yield Label("Lookup Result", classes="section-title")
                                yield Static("", id="lookup_result_view", classes="result-panel")

                    with TabPane("Contracts", id="tab_contracts"):
                        with Horizontal(classes="send-layout"):
                            with VerticalScroll(classes="send-form-column"):
                                yield Label("Contract Actions", classes="section-title")
                                yield Input(placeholder="Target contract address, account, or label", id="contract_target")
                                yield Input(placeholder="From account for writes (blank = default)", id="contract_from_account")
                                yield Input(placeholder="Network (blank = default)", id="contract_network")
                                yield Input(placeholder="ABI file path (optional)", id="contract_abi_file")
                                yield Input(placeholder="ABI fragment JSON (optional)", id="contract_abi_fragment")
                                yield Input(placeholder="Function name", id="contract_function")
                                yield Input(placeholder="Args JSON array (optional)", id="contract_args")
                                yield Input(placeholder="Native value (optional)", id="contract_value")
                                yield Input(placeholder="Gas price gwei (optional)", id="contract_gas_price")
                                yield Input(placeholder="Max fee per gas gwei (optional)", id="contract_max_fee")
                                yield Input(placeholder="Max priority fee gwei (optional)", id="contract_priority_fee")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Read", id="contract_read_button", variant="primary")
                                    yield Button("Preview Write", id="contract_preview_button")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Simulate Write", id="contract_simulate_button")
                                    yield Button("Load Defaults", id="contract_defaults_button")
                                with Vertical(classes="form-block"):
                                    yield Label("Confirmation", classes="section-title")
                                    yield Input(password=True, placeholder="Passphrase for execution", id="contract_passphrase")
                                    yield Input(placeholder="Confirmation text", id="contract_confirmation")
                                    yield Input(placeholder="Retype value for protected writes", id="contract_value_confirm")
                                    yield Button("Execute Write", id="contract_execute_button", variant="error")
                            with VerticalScroll(classes="send-preview-column"):
                                yield Label("Preview", classes="section-title")
                                yield Static("", id="contract_preview_view", classes="preview-panel")
                                yield Label("Result", classes="section-title")
                                yield Static("", id="contract_result_view", classes="result-panel")

                    with TabPane("Send", id="tab_send"):
                        with Horizontal(classes="send-layout"):
                            with VerticalScroll(classes="send-form-column"):
                                yield Label("Transaction Form", classes="section-title")
                                yield Input(placeholder="From account (blank = default)", id="send_account")
                                yield Input(placeholder="Network (blank = default)", id="send_network")
                                yield Input(placeholder="Recipient label or address", id="send_to")
                                yield Input(placeholder="Amount", id="send_amount")
                                yield Input(placeholder="Token address (optional)", id="send_token")
                                yield Input(placeholder="Gas price gwei (optional)", id="send_gas_price")
                                yield Input(placeholder="Max fee per gas gwei (optional)", id="send_max_fee")
                                yield Input(placeholder="Max priority fee gwei (optional)", id="send_priority_fee")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Load Defaults", id="send_defaults_button")
                                    yield Button("Preview Send", id="send_preview_button", variant="primary")
                                with Vertical(classes="form-block"):
                                    yield Label("Confirmation", classes="section-title")
                                    yield Input(password=True, placeholder="Passphrase for broadcast", id="send_passphrase")
                                    yield Input(placeholder="Confirmation text", id="send_confirmation")
                                    yield Input(placeholder="Retype amount for protected sends", id="send_amount_confirm")
                                    yield Button("Broadcast", id="send_broadcast_button", variant="error")
                            with VerticalScroll(classes="send-preview-column"):
                                yield Label("Preview", classes="section-title")
                                yield Static("", id="send_preview_view", classes="preview-panel")
                                yield Label("Result", classes="section-title")
                                yield Static("", id="send_result_view", classes="result-panel")

                    with TabPane("Monitor", id="tab_monitor"):
                        with Horizontal(classes="send-layout"):
                            with VerticalScroll(classes="send-form-column"):
                                yield Label("Monitoring", classes="section-title")
                                yield Input(placeholder="Account (blank = default)", id="monitor_account")
                                yield Input(placeholder="Network (blank = default)", id="monitor_network")
                                yield Input(value="10", placeholder="Poll interval seconds", id="monitor_interval")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Poll Once", id="monitor_poll_button", variant="primary")
                                    yield Button("Start", id="monitor_start_button")
                                    yield Button("Stop", id="monitor_stop_button", variant="error")
                            with VerticalScroll(classes="send-preview-column"):
                                yield Label("Monitor State", classes="section-title")
                                yield Static("", id="monitor_state_view", classes="preview-panel")
                                yield Label("Recent Events", classes="section-title")
                                yield Static("", id="monitor_events_view", classes="result-panel")

                    with TabPane("Policy", id="tab_policy"):
                        with Horizontal(classes="send-layout"):
                            with VerticalScroll(classes="send-form-column"):
                                yield Label("Policy Controls", classes="section-title")
                                yield Input(placeholder="Scope account (blank = profile)", id="policy_scope_account")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Show Policy", id="policy_refresh_button", variant="primary")
                                with Vertical(classes="form-block"):
                                    yield Label("Set / Unset Rule", classes="section-title")
                                    yield Input(placeholder="Rule name", id="policy_rule")
                                    yield Input(placeholder="Value", id="policy_value")
                                    with HorizontalScroll(classes="form-actions"):
                                        yield Button("Set Rule", id="policy_set_button", variant="primary")
                                        yield Button("Unset Rule", id="policy_unset_button", variant="error")
                                with Vertical(classes="form-block"):
                                    yield Label("Explain Action", classes="section-title")
                                    yield Input(placeholder="Account (blank = default)", id="policy_explain_account")
                                    yield Input(placeholder="Network (blank = default)", id="policy_explain_network")
                                    yield Input(placeholder="Recipient label or address", id="policy_explain_to")
                                    yield Input(placeholder="Amount", id="policy_explain_amount")
                                    yield Input(placeholder="Token address (optional)", id="policy_explain_token")
                                    yield Button("Explain", id="policy_explain_button")
                            with VerticalScroll(classes="send-preview-column"):
                                yield Label("Effective Policy", classes="section-title")
                                yield Static("", id="policy_view", classes="preview-panel")
                                yield Label("Evaluation", classes="section-title")
                                yield Static("", id="policy_explain_view", classes="result-panel")

                    with TabPane("Journal", id="tab_journal"):
                        with Horizontal(classes="master-detail"):
                            with Vertical(classes="list-column"):
                                yield Label("Journal", classes="section-title")
                                yield ListView(id="journal_list")
                            with VerticalScroll(classes="detail-column"):
                                yield Label("Journal Detail", classes="section-title")
                                yield Static("", id="journal_detail", classes="detail-panel")
                                with HorizontalScroll(classes="form-actions"):
                                    yield Button("Refresh Journal", id="journal_refresh_button", variant="primary")
                                    yield Button("Load Selected Id", id="journal_load_id_button")
                                with Vertical(classes="form-block"):
                                    yield Label("Receipt Lookup", classes="section-title")
                                    yield Input(placeholder="Tx hash (blank = selected)", id="journal_tx_hash")
                                    yield Input(placeholder="Network (optional)", id="journal_network")
                                    yield Button("Fetch Receipt", id="journal_receipt_button")
        yield RichLog(id="log_view", wrap=True, highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self.apply_theme(log_message=False)
        self.refresh_all_views(refresh_balance=True, log_message="VaultTUI loaded.")
        self.fill_balance_defaults(log_message=False)
        self.fill_lookup_defaults(log_message=False)
        self.fill_contract_defaults(log_message=False)
        self.fill_send_defaults(log_message=False)
        self.fill_monitor_defaults(log_message=False)
        self.query_one("#lookup_result_view", Static).update(self.render_lookup_result_placeholder())
        self.query_one("#contract_preview_view", Static).update(self.render_contract_preview_placeholder())
        self.query_one("#contract_result_view", Static).update(self.render_contract_result_placeholder())
        self.query_one("#send_preview_view", Static).update(self.render_send_preview_placeholder())
        self.query_one("#send_result_view", Static).update(self.render_send_result_placeholder())
        self.query_one("#policy_view", Static).update(self.render_policy_placeholder())
        self.query_one("#policy_explain_view", Static).update(self.render_policy_explain_placeholder())
        self.query_one("#monitor_state_view", Static).update(self.render_monitor_state_placeholder())
        self.query_one("#monitor_events_view", Static).update(self.render_monitor_events([]))
        if self.service.profile_name == "prod":
            self.write_log("Protected profile loaded. Use care with any send flow.")

    def action_refresh_all(self) -> None:
        self.refresh_all_views(refresh_balance=True, log_message="Refreshed all panels.")

    def action_refresh_balance(self) -> None:
        self.last_balance_snapshot = self.service.balance_snapshot()
        self.refresh_balance_views()
        self.write_log("Reloaded sidebar balance snapshot.")

    def action_show_profiles(self) -> None:
        self.switch_tab("tab_profiles", "profiles_list")

    def action_show_accounts(self) -> None:
        self.switch_tab("tab_accounts", "accounts_list")

    def action_show_networks(self) -> None:
        self.switch_tab("tab_networks", "networks_list")

    def action_show_address_book(self) -> None:
        self.switch_tab("tab_address_book", "book_list")

    def action_show_balance(self) -> None:
        self.switch_tab("tab_balance", "balance_account")

    def action_show_lookup(self) -> None:
        self.switch_tab("tab_lookup", "lookup_target")

    def action_show_contracts(self) -> None:
        self.switch_tab("tab_contracts", "contract_target")

    def action_show_send(self) -> None:
        self.switch_tab("tab_send", "send_account")

    def action_show_monitor(self) -> None:
        self.switch_tab("tab_monitor", "monitor_account")

    def action_show_policy(self) -> None:
        self.switch_tab("tab_policy", "policy_scope_account")

    def action_show_journal(self) -> None:
        self.switch_tab("tab_journal", "journal_list")

    def action_switch_to_dev(self) -> None:
        self.switch_profile("dev")

    def action_switch_to_test(self) -> None:
        self.switch_profile("test")

    def action_switch_to_prod(self) -> None:
        self.switch_profile("prod")

    def action_theme_previous(self) -> None:
        self.cycle_theme(-1)

    def action_theme_next(self) -> None:
        self.cycle_theme(1)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "refresh_button": lambda: self.refresh_all_views(refresh_balance=True, log_message="Refreshed all panels."),
            "refresh_balance_button": self.action_refresh_balance,
            "profile_dev": lambda: self.switch_profile("dev"),
            "profile_test": lambda: self.switch_profile("test"),
            "profile_prod": lambda: self.switch_profile("prod"),
            "theme_prev_button": lambda: self.cycle_theme(-1),
            "theme_next_button": lambda: self.cycle_theme(1),
            "profiles_activate_button": self.activate_selected_profile,
            "account_set_default_button": self.set_selected_account_default,
            "account_use_forms_button": self.use_selected_account_in_forms,
            "account_create_button": self.create_account,
            "account_import_button": self.import_account,
            "account_watch_button": self.add_watch_account,
            "network_set_default_button": self.set_selected_network_default,
            "network_use_forms_button": self.use_selected_network_in_forms,
            "network_anvil_button": self.add_anvil_network,
            "network_alchemy_button": self.add_alchemy_network,
            "book_add_button": self.add_book_entry,
            "book_use_selected_button": self.use_selected_book_in_send,
            "book_remove_selected_button": self.remove_selected_book_entry,
            "balance_button": self.fetch_balance,
            "balance_defaults_button": self.fill_balance_defaults,
            "lookup_address_button": self.lookup_address,
            "lookup_token_button": self.lookup_token,
            "lookup_contract_button": self.lookup_contract,
            "lookup_defaults_button": self.fill_lookup_defaults,
            "contract_read_button": self.contract_read,
            "contract_preview_button": self.preview_contract_write,
            "contract_simulate_button": self.simulate_contract_write,
            "contract_defaults_button": self.fill_contract_defaults,
            "contract_execute_button": self.execute_contract_write,
            "send_defaults_button": self.fill_send_defaults,
            "send_preview_button": self.preview_send,
            "send_broadcast_button": self.broadcast_send,
            "monitor_poll_button": self.monitor_poll_once,
            "monitor_start_button": self.start_monitoring,
            "monitor_stop_button": self.stop_monitoring,
            "policy_refresh_button": self.refresh_policy_view,
            "policy_set_button": self.set_policy_rule,
            "policy_unset_button": self.unset_policy_rule,
            "policy_explain_button": self.explain_policy_action,
            "journal_refresh_button": self.refresh_journal_view,
            "journal_load_id_button": self.load_selected_journal_id,
            "journal_receipt_button": self.fetch_journal_receipt,
        }
        handler = handlers.get(event.button.id or "")
        if handler:
            self.run_safe(handler)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if isinstance(item, EntityListItem):
            self.update_detail_for_list(event.list_view.id or "", item.entity_name)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, EntityListItem):
            self.update_detail_for_list(event.list_view.id or "", item.entity_name)

    def on_input_changed(self, event: Input.Changed) -> None:
        if (event.input.id or "") in SEND_INPUT_IDS:
            self.invalidate_send_preview()
        if (event.input.id or "") in CONTRACT_INPUT_IDS:
            self.invalidate_contract_preview()

    def on_unmount(self) -> None:
        self.stop_monitoring(log_message=False)

    def run_safe(self, fn: Any) -> None:
        try:
            fn()
        except VaultError as exc:
            self.write_log(f"[red]Error:[/red] {exc}")
        except Exception as exc:  # pragma: no cover - UI fallback
            self.write_log(f"[red]Unexpected error:[/red] {exc}")

    def refresh_all_views(self, refresh_balance: bool = False, log_message: str | None = None) -> None:
        profiles_payload = self.service.list_profiles()
        accounts_payload = self.service.list_accounts()
        networks_payload = self.service.list_networks()
        book_payload = self.service.list_address_book()
        journal_payload = self.service.list_journal()

        self.profile_rows = profiles_payload["profiles"]
        self.account_rows = accounts_payload["accounts"]
        self.network_rows = networks_payload["networks"]
        self.book_rows = book_payload["entries"]
        self.journal_rows = journal_payload["entries"]

        self.refresh_sidebar(refresh_balance=refresh_balance)
        self.refresh_master_detail_lists(accounts_payload, networks_payload, profiles_payload, journal_payload)
        self.refresh_context_bar()
        self.query_one("#profiles_detail", Static).update(self.render_profile_detail(self.find_row(self.profile_rows, self.selected_profile_name)))
        self.query_one("#accounts_detail", Static).update(self.render_account_detail(self.find_row(self.account_rows, self.selected_account_name)))
        self.query_one("#networks_detail", Static).update(self.render_network_detail(self.find_row(self.network_rows, self.selected_network_name)))
        self.query_one("#book_detail", Static).update(self.render_book_detail(self.find_row(self.book_rows, self.selected_book_name)))
        self.query_one("#journal_detail", Static).update(self.render_journal_detail(self.find_journal_row(self.selected_journal_id)))
        self.refresh_policy_view(log_message=False)
        self.refresh_monitor_views(log_message=False)
        if log_message:
            self.write_log(log_message)

    def refresh_sidebar(self, refresh_balance: bool = False) -> None:
        context = self.service.context_summary()
        safety = self.service.safety_status()
        if refresh_balance or self.last_balance_snapshot is None:
            self.last_balance_snapshot = self.service.balance_snapshot()
        self.query_one("#status_profile", Static).update(self.render_profile_card(context))
        self.query_one("#status_account", Static).update(self.render_account_card(context))
        self.query_one("#status_network", Static).update(self.render_network_card(context))
        self.query_one("#status_balance", Static).update(self.render_balance_card(self.last_balance_snapshot))
        self.query_one("#status_safety", Static).update(self.render_safety_card(safety))

    def refresh_context_bar(self) -> None:
        context = self.service.context_summary()
        self.query_one("#context_bar", Static).update(self.render_context_bar(context))

    def refresh_master_detail_lists(
        self,
        accounts_payload: dict[str, Any],
        networks_payload: dict[str, Any],
        profiles_payload: dict[str, Any],
        journal_payload: dict[str, Any],
    ) -> None:
        self.rebuild_list("profiles_list", self.profile_rows, self.make_profile_item, self.selected_profile_name or profiles_payload["active_profile"])
        self.rebuild_list("accounts_list", self.account_rows, self.make_account_item, self.selected_account_name or accounts_payload.get("default_account"))
        self.rebuild_list("networks_list", self.network_rows, self.make_network_item, self.selected_network_name or networks_payload.get("default_network"))
        self.rebuild_list("book_list", self.book_rows, self.make_book_item, self.selected_book_name)
        self.rebuild_list("journal_list", self.journal_rows, self.make_journal_item, self.selected_journal_id or first_journal_id(journal_payload["entries"]))

    def rebuild_list(self, list_id: str, rows: list[dict[str, Any]], item_builder: Any, preferred_name: str | None) -> None:
        list_view = self.query_one(f"#{list_id}", ListView)
        list_view.clear()
        items = [item_builder(row) for row in rows]
        list_view.extend(items)
        identities = [item.entity_name for item in items if isinstance(item, EntityListItem)]
        self.call_after_refresh(self.sync_list_selection, list_id, identities, preferred_name)

    def sync_list_selection(self, list_id: str, identities: list[str], preferred_name: str | None) -> None:
        list_view = self.query_one(f"#{list_id}", ListView)
        if not identities:
            list_view.index = None
            return
        index = 0
        if preferred_name:
            for idx, identity in enumerate(identities):
                if identity == preferred_name:
                    index = idx
                    break
        list_view.index = index

    def switch_profile(self, name: str) -> None:
        self.ensure_profile_allowed(name)
        payload = self.service.use_profile(name)
        self.current_theme_name = self.service.show_theme()["name"]
        self.last_preview = None
        self.last_contract_preview = None
        self.last_balance_snapshot = None
        self.last_lookup_result = None
        self.monitor_recent_events = []
        self.monitor_last_payload = None
        self.selected_profile_name = name
        self.selected_account_name = None
        self.selected_network_name = None
        self.selected_book_name = None
        self.selected_journal_id = None
        self.stop_monitoring(log_message=False)
        self.refresh_all_views(refresh_balance=True, log_message=f"Switched to profile {payload['name']}.")
        self.fill_balance_defaults(log_message=False)
        self.fill_lookup_defaults(log_message=False)
        self.fill_contract_defaults(log_message=False)
        self.fill_send_defaults(log_message=False)
        self.fill_monitor_defaults(log_message=False)
        self.query_one("#lookup_result_view", Static).update(self.render_lookup_result_placeholder())
        self.query_one("#contract_preview_view", Static).update(self.render_contract_preview_placeholder())
        self.query_one("#contract_result_view", Static).update(self.render_contract_result_placeholder())
        self.query_one("#send_preview_view", Static).update(self.render_send_preview_placeholder())
        self.query_one("#send_result_view", Static).update(self.render_send_result_placeholder())
        self.query_one("#monitor_state_view", Static).update(self.render_monitor_state_placeholder())
        self.query_one("#monitor_events_view", Static).update(self.render_monitor_events([]))
        self.apply_theme(log_message=False)

    def activate_selected_profile(self) -> None:
        if not self.selected_profile_name:
            raise VaultError("No profile selected.")
        self.switch_profile(self.selected_profile_name)

    def create_account(self) -> None:
        passphrase = self.value("account_create_passphrase")
        if passphrase != self.value("account_create_passphrase_confirm"):
            raise VaultError("Passphrases do not match.")
        payload = self.service.create_account(self.value("account_create_name"), passphrase, set_default=True)
        self.selected_account_name = payload["name"]
        self.last_balance_snapshot = None
        self.refresh_all_views(refresh_balance=True, log_message=payload["summary"])

    def import_account(self) -> None:
        passphrase = self.value("account_import_passphrase")
        if passphrase != self.value("account_import_passphrase_confirm"):
            raise VaultError("Passphrases do not match.")
        payload = self.service.import_account(
            name=self.value("account_import_name"),
            private_key_hex=self.value("account_import_private_key"),
            passphrase=passphrase,
            set_default=True,
        )
        self.selected_account_name = payload["name"]
        self.last_balance_snapshot = None
        self.refresh_all_views(refresh_balance=True, log_message=payload["summary"])

    def add_watch_account(self) -> None:
        payload = self.service.add_watch_only_account(
            self.value("account_watch_name"),
            self.value("account_watch_address"),
            set_default=not self.account_rows,
        )
        self.selected_account_name = payload["name"]
        self.refresh_all_views(log_message=payload["summary"])

    def set_selected_account_default(self) -> None:
        if not self.selected_account_name:
            raise VaultError("No account selected.")
        payload = self.service.use_account(self.selected_account_name)
        self.last_balance_snapshot = None
        self.refresh_all_views(refresh_balance=True, log_message=payload["summary"])

    def add_anvil_network(self) -> None:
        payload = self.service.add_anvil_network(
            name=self.value("network_anvil_name") or "local",
            rpc_url=self.value("network_anvil_rpc_url") or "http://127.0.0.1:8545",
            chain_id=int(self.value("network_anvil_chain_id") or "31337"),
            symbol=self.value("network_anvil_symbol") or "ETH",
            set_default=True,
        )
        self.selected_network_name = payload["name"]
        self.last_balance_snapshot = None
        self.refresh_all_views(refresh_balance=True, log_message=payload["summary"])

    def add_alchemy_network(self) -> None:
        payload = self.service.add_alchemy_network(
            preset=self.value("network_alchemy_preset"),
            name=self.value("network_alchemy_name") or None,
            api_key_env=self.value("network_alchemy_env") or "ALCHEMY_API_KEY",
            set_default=True,
        )
        self.selected_network_name = payload["name"]
        self.last_balance_snapshot = None
        self.refresh_all_views(refresh_balance=True, log_message=payload["summary"])

    def set_selected_network_default(self) -> None:
        if not self.selected_network_name:
            raise VaultError("No network selected.")
        payload = self.service.use_network(self.selected_network_name)
        self.last_balance_snapshot = None
        self.refresh_all_views(refresh_balance=True, log_message=payload["summary"])

    def add_book_entry(self) -> None:
        payload = self.service.add_address_book_entry(
            self.value("book_name"),
            self.value("book_address"),
            network_scope=self.value("book_network") or None,
            notes=self.value("book_notes") or None,
        )
        self.selected_book_name = payload["name"]
        self.refresh_all_views(log_message=payload["summary"])

    def remove_selected_book_entry(self) -> None:
        if not self.selected_book_name:
            raise VaultError("No address book entry selected.")
        payload = self.service.remove_address_book_entry(self.selected_book_name)
        self.selected_book_name = None
        self.refresh_all_views(log_message=payload["summary"])

    def fill_balance_defaults(self, log_message: bool = True) -> None:
        context = self.service.context_summary()
        if context["default_account"]:
            self.set_value("balance_account", context["default_account"]["name"])
        if context["default_network"]:
            self.set_value("balance_network", context["default_network"]["name"])
        if log_message:
            self.write_log("Loaded default account and network into the balance form.")

    def fill_lookup_defaults(self, log_message: bool = True) -> None:
        context = self.service.context_summary()
        if context["default_network"]:
            self.set_value("lookup_network", context["default_network"]["name"])
        if log_message:
            self.write_log("Loaded the default network into the lookup form.")

    def fill_contract_defaults(self, log_message: bool = True) -> None:
        context = self.service.context_summary()
        if context["default_account"]:
            self.set_value("contract_from_account", context["default_account"]["name"])
        if context["default_network"]:
            self.set_value("contract_network", context["default_network"]["name"])
        if log_message:
            self.write_log("Loaded default account and network into the contract form.")

    def fill_send_defaults(self, log_message: bool = True) -> None:
        context = self.service.context_summary()
        if context["default_account"]:
            self.set_value("send_account", context["default_account"]["name"])
        if context["default_network"]:
            self.set_value("send_network", context["default_network"]["name"])
        if log_message:
            self.write_log("Loaded default account and network into the send form.")

    def fill_monitor_defaults(self, log_message: bool = True) -> None:
        context = self.service.context_summary()
        if context["default_account"]:
            self.set_value("monitor_account", context["default_account"]["name"])
        if context["default_network"]:
            self.set_value("monitor_network", context["default_network"]["name"])
        if log_message:
            self.write_log("Loaded default account and network into the monitor form.")

    def use_selected_account_in_forms(self) -> None:
        if not self.selected_account_name:
            raise VaultError("No account selected.")
        self.set_value("balance_account", self.selected_account_name)
        self.set_value("lookup_target", self.selected_account_name)
        self.set_value("contract_from_account", self.selected_account_name)
        self.set_value("send_account", self.selected_account_name)
        self.set_value("monitor_account", self.selected_account_name)
        self.write_log(f"Loaded account {self.selected_account_name} into active forms.")

    def use_selected_network_in_forms(self) -> None:
        if not self.selected_network_name:
            raise VaultError("No network selected.")
        self.set_value("balance_network", self.selected_network_name)
        self.set_value("lookup_network", self.selected_network_name)
        self.set_value("contract_network", self.selected_network_name)
        self.set_value("send_network", self.selected_network_name)
        self.set_value("monitor_network", self.selected_network_name)
        self.write_log(f"Loaded network {self.selected_network_name} into active forms.")

    def use_selected_book_in_send(self) -> None:
        row = self.find_row(self.book_rows, self.selected_book_name)
        if not row:
            raise VaultError("No address book entry selected.")
        self.set_value("send_to", row["name"])
        network_scope = row.get("network_scope")
        if network_scope and network_scope != "any":
            self.set_value("send_network", network_scope)
        self.switch_tab("tab_send", "send_amount")
        self.write_log(f"Loaded recipient {row['name']} into the send form.")

    def fetch_balance(self) -> None:
        self.last_balance_snapshot = self.service.balance_snapshot(
            account_name=self.value("balance_account") or None,
            network_name=self.value("balance_network") or None,
            token_address=self.value("balance_token") or None,
        )
        self.refresh_balance_views()
        self.write_log(self.last_balance_snapshot["summary"])

    def refresh_balance_views(self) -> None:
        snapshot = self.last_balance_snapshot or self.service.balance_snapshot()
        self.query_one("#balance_snapshot_view", Static).update(self.render_balance_snapshot(snapshot))
        self.query_one("#status_balance", Static).update(self.render_balance_card(snapshot))

    def lookup_address(self) -> None:
        self.last_lookup_result = self.service.lookup_address(
            target=self.value("lookup_target"),
            network_name=self.value("lookup_network") or None,
        )
        self.query_one("#lookup_result_view", Static).update(self.render_lookup_result(self.last_lookup_result))
        self.write_log(self.last_lookup_result["summary"])

    def lookup_token(self) -> None:
        self.last_lookup_result = self.service.lookup_token(
            target=self.value("lookup_target"),
            network_name=self.value("lookup_network") or None,
            holder=self.value("lookup_holder") or None,
        )
        self.query_one("#lookup_result_view", Static).update(self.render_lookup_result(self.last_lookup_result))
        self.write_log(self.last_lookup_result["summary"])

    def lookup_contract(self) -> None:
        self.last_lookup_result = self.service.lookup_contract(
            target=self.value("lookup_target"),
            network_name=self.value("lookup_network") or None,
        )
        self.query_one("#lookup_result_view", Static).update(self.render_lookup_result(self.last_lookup_result))
        self.write_log(self.last_lookup_result["summary"])

    def contract_read(self) -> None:
        payload = self.service.contract_read(
            target=self.value("contract_target"),
            function_name=self.value("contract_function"),
            abi_file=self.value("contract_abi_file") or None,
            abi_fragment=self.value("contract_abi_fragment") or None,
            args_json=self.value("contract_args") or None,
            network_name=self.value("contract_network") or None,
        )
        self.query_one("#contract_result_view", Static).update(self.render_contract_result(payload))
        self.write_log(payload["summary"])

    def preview_contract_write(self) -> None:
        preview = self.service.preview_contract_write(
            from_account_name=self.value("contract_from_account"),
            target=self.value("contract_target"),
            function_name=self.value("contract_function"),
            abi_file=self.value("contract_abi_file") or None,
            abi_fragment=self.value("contract_abi_fragment") or None,
            args_json=self.value("contract_args") or None,
            value=self.value("contract_value") or None,
            network_name=self.value("contract_network") or None,
            gas_price_gwei=self.value("contract_gas_price") or None,
            max_fee_per_gas_gwei=self.value("contract_max_fee") or None,
            max_priority_fee_per_gas_gwei=self.value("contract_priority_fee") or None,
        )
        self.last_contract_preview = preview
        self.query_one("#contract_preview_view", Static).update(self.render_contract_preview(preview))
        self.query_one("#contract_result_view", Static).update(self.render_contract_result_placeholder())
        self.call_after_refresh(lambda: self.query_one("#contract_passphrase", Input).focus())
        if preview["requires_strong_confirmation"]:
            self.write_log("Protected contract preview ready. Enter destination suffix and value to execute.")
        else:
            self.write_log("Contract preview ready. Enter YES to execute.")

    def simulate_contract_write(self) -> None:
        payload = self.service.simulate_contract_write(
            from_account_name=self.value("contract_from_account"),
            target=self.value("contract_target"),
            function_name=self.value("contract_function"),
            abi_file=self.value("contract_abi_file") or None,
            abi_fragment=self.value("contract_abi_fragment") or None,
            args_json=self.value("contract_args") or None,
            value=self.value("contract_value") or None,
            network_name=self.value("contract_network") or None,
            gas_price_gwei=self.value("contract_gas_price") or None,
            max_fee_per_gas_gwei=self.value("contract_max_fee") or None,
            max_priority_fee_per_gas_gwei=self.value("contract_priority_fee") or None,
        )
        self.query_one("#contract_result_view", Static).update(self.render_contract_result(payload))
        self.write_log(payload["summary"])

    def execute_contract_write(self) -> None:
        if not self.last_contract_preview:
            raise VaultError("No contract preview available. Preview the write first.")
        current_preview = self.service.preview_contract_write(
            from_account_name=self.value("contract_from_account"),
            target=self.value("contract_target"),
            function_name=self.value("contract_function"),
            abi_file=self.value("contract_abi_file") or None,
            abi_fragment=self.value("contract_abi_fragment") or None,
            args_json=self.value("contract_args") or None,
            value=self.value("contract_value") or None,
            network_name=self.value("contract_network") or None,
            gas_price_gwei=self.value("contract_gas_price") or None,
            max_fee_per_gas_gwei=self.value("contract_max_fee") or None,
            max_priority_fee_per_gas_gwei=self.value("contract_priority_fee") or None,
        )
        if preview_fingerprint(current_preview) != preview_fingerprint(self.last_contract_preview):
            self.last_contract_preview = None
            self.query_one("#contract_preview_view", Static).update(self.render_contract_preview_placeholder())
            raise VaultError("Contract form changed after preview. Preview the write again before executing.")
        confirmation = self.value("contract_confirmation")
        if self.last_contract_preview["requires_strong_confirmation"]:
            expected = self.last_contract_preview["to_address"][-6:]
            if confirmation != expected:
                raise VaultError(f"Confirmation text must equal {expected}.")
            if self.value("contract_value_confirm") != (self.last_contract_preview.get("value") or "0"):
                raise VaultError("Retyped value does not match the preview.")
        elif confirmation != "YES":
            raise VaultError("Confirmation text must equal YES.")
        payload = self.service.execute_contract_write(self.value("contract_passphrase"), preview=self.last_contract_preview)
        self.query_one("#contract_result_view", Static).update(self.render_contract_result(payload))
        self.refresh_sidebar(refresh_balance=True)
        self.refresh_all_views(log_message=f"Broadcasted transaction {payload['transaction_hash']}")

    def preview_send(self) -> None:
        preview = self.service.preview_send(
            from_account_name=self.value("send_account") or None,
            network_name=self.value("send_network") or None,
            recipient=self.value("send_to"),
            amount=self.value("send_amount"),
            token_address=self.value("send_token") or None,
            gas_price_gwei=self.value("send_gas_price") or None,
            max_fee_per_gas_gwei=self.value("send_max_fee") or None,
            max_priority_fee_per_gas_gwei=self.value("send_priority_fee") or None,
        )
        self.last_preview = preview
        self.query_one("#send_preview_view", Static).update(self.render_send_preview(preview))
        self.query_one("#send_result_view", Static).update(self.render_send_result_placeholder())
        self.call_after_refresh(lambda: self.query_one("#send_passphrase", Input).focus())
        if preview["requires_strong_confirmation"]:
            self.write_log("Protected send preview ready. Enter destination suffix and amount to broadcast.")
        else:
            self.write_log("Send preview ready. Enter YES to broadcast.")

    def broadcast_send(self) -> None:
        if not self.last_preview:
            raise VaultError("No preview available. Preview the transaction first.")
        current_preview = self.service.preview_send(
            from_account_name=self.value("send_account") or None,
            network_name=self.value("send_network") or None,
            recipient=self.value("send_to"),
            amount=self.value("send_amount"),
            token_address=self.value("send_token") or None,
            gas_price_gwei=self.value("send_gas_price") or None,
            max_fee_per_gas_gwei=self.value("send_max_fee") or None,
            max_priority_fee_per_gas_gwei=self.value("send_priority_fee") or None,
        )
        if preview_fingerprint(current_preview) != preview_fingerprint(self.last_preview):
            self.last_preview = None
            self.query_one("#send_preview_view", Static).update(self.render_send_preview_placeholder())
            raise VaultError("Send form changed after preview. Preview the transaction again before broadcasting.")
        confirmation = self.value("send_confirmation")
        if self.last_preview["requires_strong_confirmation"]:
            expected = self.last_preview["to_address"][-6:]
            if confirmation != expected:
                raise VaultError(f"Confirmation text must equal {expected}.")
            if self.value("send_amount_confirm") != self.last_preview["amount"]:
                raise VaultError("Retyped amount does not match the preview.")
        elif confirmation != "YES":
            raise VaultError("Confirmation text must equal YES.")
        payload = self.service.execute_send(self.value("send_passphrase"), preview=self.last_preview)
        self.query_one("#send_result_view", Static).update(self.render_send_result(payload))
        self.last_balance_snapshot = None
        self.refresh_sidebar(refresh_balance=True)
        self.refresh_all_views(log_message=f"Broadcasted transaction {payload['transaction_hash']}")

    def refresh_policy_view(self, log_message: bool = True) -> None:
        payload = self.service.show_policy(self.value("policy_scope_account") or None)
        self.query_one("#policy_view", Static).update(self.render_policy_view(payload))
        if log_message:
            self.write_log(payload["summary"])

    def set_policy_rule(self) -> None:
        payload = self.service.set_policy_rule(
            self.value("policy_rule"),
            self.value("policy_value"),
            self.value("policy_scope_account") or None,
        )
        self.refresh_policy_view(log_message=False)
        self.query_one("#policy_explain_view", Static).update(self.render_policy_explain_placeholder())
        self.write_log(payload["summary"])

    def unset_policy_rule(self) -> None:
        payload = self.service.unset_policy_rule(self.value("policy_rule"), self.value("policy_scope_account") or None)
        self.refresh_policy_view(log_message=False)
        self.query_one("#policy_explain_view", Static).update(self.render_policy_explain_placeholder())
        self.write_log(payload["summary"])

    def explain_policy_action(self) -> None:
        payload = self.service.explain_policy_action(
            account_name=self.value("policy_explain_account") or None,
            network_name=self.value("policy_explain_network") or None,
            recipient=self.value("policy_explain_to"),
            amount=self.value("policy_explain_amount"),
            token_address=self.value("policy_explain_token") or None,
        )
        self.query_one("#policy_explain_view", Static).update(self.render_policy_explain(payload))
        self.write_log(payload["summary"])

    def refresh_journal_view(self) -> None:
        self.refresh_all_views(log_message="Refreshed journal.")

    def load_selected_journal_id(self) -> None:
        row = self.find_journal_row(self.selected_journal_id)
        if not row:
            raise VaultError("No journal entry selected.")
        self.set_value("journal_tx_hash", row.get("tx_hash") or "")
        if row.get("network"):
            self.set_value("journal_network", row["network"])
        self.write_log(f"Loaded journal entry {row['id']}.")

    def fetch_journal_receipt(self) -> None:
        tx_hash = self.value("journal_tx_hash")
        if not tx_hash:
            row = self.find_journal_row(self.selected_journal_id)
            tx_hash = (row or {}).get("tx_hash") or ""
        if not tx_hash:
            raise VaultError("Provide a transaction hash or select a transaction-backed journal entry first.")
        payload = self.service.show_receipt(tx_hash, self.value("journal_network") or None)
        self.query_one("#journal_detail", Static).update(self.render_receipt_detail(payload))
        self.write_log(payload["summary"])

    def monitor_poll_once(self) -> None:
        payload = self.service.monitor_poll(
            account_name=self.value("monitor_account") or None,
            network_name=self.value("monitor_network") or None,
        )
        self.capture_monitor_payload(payload)
        self.refresh_all_views(log_message=f"Monitor poll recorded {payload['new_event_count']} new event(s).")

    def start_monitoring(self) -> None:
        self.stop_monitoring(log_message=False)
        interval = max(1, int_or_none(self.value("monitor_interval")) or 10)
        self.monitor_timer = self.set_interval(interval, self.monitor_tick)
        self.write_log(f"Started monitoring every {interval}s.")

    def stop_monitoring(self, log_message: bool = True) -> None:
        if self.monitor_timer is not None:
            self.monitor_timer.stop()
            self.monitor_timer = None
            if log_message:
                self.write_log("Stopped monitoring.")

    def monitor_tick(self) -> None:
        self.run_safe(self.monitor_poll_once)

    def capture_monitor_payload(self, payload: dict[str, Any]) -> None:
        self.monitor_last_payload = payload
        self.monitor_recent_events = (payload["new_events"] + self.monitor_recent_events)[:10]
        self.query_one("#monitor_state_view", Static).update(self.render_monitor_state(payload))
        self.query_one("#monitor_events_view", Static).update(self.render_monitor_events(self.monitor_recent_events))

    def refresh_monitor_views(self, log_message: bool = False) -> None:
        try:
            payload = self.service.monitor_show_state(
                account_name=self.value("monitor_account") or None,
                network_name=self.value("monitor_network") or None,
            )
        except Exception:
            self.query_one("#monitor_state_view", Static).update(self.render_monitor_state_placeholder())
            self.query_one("#monitor_events_view", Static).update(self.render_monitor_events(self.monitor_recent_events))
            return
        self.query_one("#monitor_state_view", Static).update(self.render_monitor_state(payload))
        if not self.monitor_recent_events:
            try:
                events_payload = self.service.monitor_list_events(
                    account_name=self.value("monitor_account") or None,
                    network_name=self.value("monitor_network") or None,
                    limit=10,
                )
                self.monitor_recent_events = events_payload["events"]
            except Exception:
                self.monitor_recent_events = []
        self.query_one("#monitor_events_view", Static).update(self.render_monitor_events(self.monitor_recent_events))
        if log_message:
            self.write_log(payload["summary"])

    def switch_tab(self, tab_id: str, focus_id: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab_id
        self.call_after_refresh(lambda: self.query_one(f"#{focus_id}").focus())

    def value(self, widget_id: str) -> str:
        return self.query_one(f"#{widget_id}", Input).value.strip()

    def set_value(self, widget_id: str, value: str) -> None:
        self.query_one(f"#{widget_id}", Input).value = value

    def write_log(self, message: str) -> None:
        if message == self._last_log_message:
            return
        self._last_log_message = message
        self.query_one("#log_view", RichLog).write(message)

    def ensure_profile_allowed(self, name: str) -> None:
        if name == "prod" and not self.allow_prod:
            raise VaultError("Refusing to open the UI on `prod` without `--allow-prod`.")

    def cycle_theme(self, step: int) -> None:
        next_theme = cycle_theme_name(self.current_theme_name, step=step)
        payload = self.service.use_theme(next_theme)
        self.current_theme_name = payload["name"]
        self.apply_theme()
        self.refresh_all_views(log_message=f"Theme set to {payload['name']}.")

    def apply_theme(self, log_message: bool = False) -> None:
        self.theme = resolve_textual_theme(self.current_theme_name)
        if log_message:
            self.write_log(f"Theme set to {self.current_theme_name}.")

    def invalidate_send_preview(self) -> None:
        if not self.last_preview:
            return
        self.last_preview = None
        self.query_one("#send_preview_view", Static).update(self.render_send_preview_placeholder())
        self.query_one("#send_result_view", Static).update(self.render_send_result_placeholder())

    def invalidate_contract_preview(self) -> None:
        if not self.last_contract_preview:
            return
        self.last_contract_preview = None
        self.query_one("#contract_preview_view", Static).update(self.render_contract_preview_placeholder())
        self.query_one("#contract_result_view", Static).update(self.render_contract_result_placeholder())

    def find_row(self, rows: list[dict[str, Any]], name: str | None) -> dict[str, Any] | None:
        if not name:
            return rows[0] if rows else None
        for row in rows:
            if row["name"] == name:
                return row
        return rows[0] if rows else None

    def find_journal_row(self, entry_id: str | None) -> dict[str, Any] | None:
        if not entry_id:
            return self.journal_rows[0] if self.journal_rows else None
        for row in self.journal_rows:
            if row["id"] == entry_id:
                return row
        return self.journal_rows[0] if self.journal_rows else None

    def update_detail_for_list(self, list_id: str, entity_name: str) -> None:
        if list_id == "profiles_list":
            self.selected_profile_name = entity_name
            self.query_one("#profiles_detail", Static).update(self.render_profile_detail(self.find_row(self.profile_rows, entity_name)))
        elif list_id == "accounts_list":
            self.selected_account_name = entity_name
            self.query_one("#accounts_detail", Static).update(self.render_account_detail(self.find_row(self.account_rows, entity_name)))
        elif list_id == "networks_list":
            self.selected_network_name = entity_name
            self.query_one("#networks_detail", Static).update(self.render_network_detail(self.find_row(self.network_rows, entity_name)))
        elif list_id == "book_list":
            self.selected_book_name = entity_name
            self.query_one("#book_detail", Static).update(self.render_book_detail(self.find_row(self.book_rows, entity_name)))
        elif list_id == "journal_list":
            self.selected_journal_id = entity_name
            self.query_one("#journal_detail", Static).update(self.render_journal_detail(self.find_journal_row(entity_name)))

    def make_profile_item(self, row: dict[str, Any]) -> EntityListItem:
        status = "active" if row["is_active"] else "inactive"
        data = "data" if row["has_data"] else "empty"
        return EntityListItem(row["name"], row["name"], f"{status} · {data}")

    def make_account_item(self, row: dict[str, Any]) -> EntityListItem:
        marker = "*" if row["is_default"] else " "
        return EntityListItem(row["name"], f"{marker} {row['name']}", shorten_address(row["address"]))

    def make_network_item(self, row: dict[str, Any]) -> EntityListItem:
        marker = "*" if row["is_default"] else " "
        provider = row.get("provider", "custom")
        return EntityListItem(row["name"], f"{marker} {row['name']}", f"{provider} · chain {row['chain_id']}")

    def make_book_item(self, row: dict[str, Any]) -> EntityListItem:
        scope = row.get("network_scope") or "any"
        return EntityListItem(row["name"], row["name"], f"{scope} · {shorten_address(row['address'])}")

    def make_journal_item(self, row: dict[str, Any]) -> EntityListItem:
        title = shorten_hash(row["id"]) if row.get("origin") == "monitor" else shorten_hash(row.get("tx_hash") or row["id"])
        subtitle = f"{row.get('origin', 'system')} · {row.get('event_type', row.get('action', 'event'))} · {row.get('status') or '-'}"
        return EntityListItem(row["id"], title, subtitle)

    def render_profile_card(self, context: dict[str, Any]) -> str:
        badge = "PROTECTED" if context["is_protected_profile"] else "WORKSPACE"
        return (
            f"[b]Profile[/b]\n"
            f"{context['profile']} · {badge}\n"
            f"Accounts: {context['account_count']}\n"
            f"Networks: {context['network_count']}\n"
            f"Theme: {context['theme']}"
        )

    def render_context_bar(self, context: dict[str, Any]) -> str:
        account = context["default_account"]
        network = context["default_network"]
        account_text = account["name"] if account else "No default account"
        if account:
            account_text += f" · {shorten_address(account['address'])}"
        network_text = network["name"] if network else "No default network"
        if network:
            network_text += f" · chain {network['chain_id']}"
        return (
            f"[b]Active Context[/b]\n"
            f"Profile: {context['profile']}\n"
            f"Theme: {context['theme']}\n"
            f"Account: {account_text}\n"
            f"Network: {network_text}\n"
            f"Safety State: {context['safety_state']}"
        )

    def render_account_card(self, context: dict[str, Any]) -> str:
        account = context["default_account"]
        if not account:
            return "[b]Default Account[/b]\nNot set"
        return f"[b]Default Account[/b]\n{account['name']}\n{shorten_address(account['address'])}"

    def render_network_card(self, context: dict[str, Any]) -> str:
        network = context["default_network"]
        if not network:
            return "[b]Default Network[/b]\nNot set"
        return f"[b]Default Network[/b]\n{network['name']}\n{network.get('provider', 'custom')} · {network['chain_id']}"

    def render_balance_card(self, snapshot: dict[str, Any] | None) -> str:
        if not snapshot:
            return "[b]Balance Snapshot[/b]\nNot loaded"
        if snapshot["status"] != "ok":
            return (
                "[b]Balance Snapshot[/b]\n"
                f"{snapshot['status']}\n"
                f"{snapshot.get('account_name') or '-'} @ {snapshot.get('network_name') or '-'}\n"
                f"{snapshot['message']}"
            )
        return f"[b]Balance Snapshot[/b]\n{snapshot['balance']} {snapshot['symbol']}\n{snapshot['account_name']} @ {snapshot['network']}"

    def render_safety_card(self, safety: dict[str, Any]) -> str:
        finding = safety["findings"][0] if safety["findings"] else "No immediate issues detected."
        issue_count = 0 if finding == "No immediate safety issues detected." else len(safety["findings"])
        return (
            "[b]Safety[/b]\n"
            f"Issues: {issue_count}\n"
            f"Prod default: {safety.get('prod_default_account') or '-'} / {safety.get('prod_default_network') or '-'}\n"
            f"{finding}"
        )

    def render_profile_detail(self, row: dict[str, Any] | None) -> str:
        if not row:
            return "No profiles available."
        return (
            f"[b]{row['name']}[/b]\n"
            f"Active: {yes_no(row['is_active'])}\n"
            f"Has Data: {yes_no(row['has_data'])}\n"
            f"Legacy Home: {yes_no(row['uses_legacy_home'])}\n"
            f"Storage Path:\n{row['storage_path']}"
        )

    def render_account_detail(self, row: dict[str, Any] | None) -> str:
        if not row:
            return "No accounts available."
        role = "[green]default[/green]" if row["is_default"] else "secondary"
        return (
            f"[b]{row['name']}[/b]\n"
            f"Role: {role}\n"
            f"Address: {row['address']}\n"
            f"Source: {row['source']}\n"
            f"Signer Type: {row.get('signer_type') or '-'}\n"
            f"Created: {row.get('created_at') or '-'}"
        )

    def render_network_detail(self, row: dict[str, Any] | None) -> str:
        if not row:
            return "No networks available."
        protected = "yes" if int(row["chain_id"]) in {1, 10, 137, 8453, 42161} else "no"
        return (
            f"[b]{row['name']}[/b]\n"
            f"Default: {yes_no(row['is_default'])}\n"
            f"Provider: {row.get('provider', 'custom')}\n"
            f"Chain ID: {row['chain_id']}\n"
            f"Symbol: {row['symbol']}\n"
            f"Protected Network: {protected}\n"
            f"RPC: {row.get('rpc_url', '-')}"
        )

    def render_book_detail(self, row: dict[str, Any] | None) -> str:
        if not row:
            return "No address book entries available."
        return (
            f"[b]{row['name']}[/b]\n"
            f"Address: {row['address']}\n"
            f"Scope: {row.get('network_scope') or 'any'}\n"
            f"Notes: {row.get('notes') or '-'}"
        )

    def render_journal_detail(self, row: dict[str, Any] | None) -> str:
        if not row:
            return "No journal entries available."
        details = row.get("details")
        details_text = pretty_json(details) if isinstance(details, dict) else (details or "-")
        return (
            f"[b]{row.get('event_type', row.get('action', 'event'))}[/b]\n"
            f"Id: {row['id']}\n"
            f"Origin: {row.get('origin') or '-'}\n"
            f"Kind: {row.get('kind') or '-'}\n"
            f"Status: {row.get('status') or '-'}\n"
            f"Profile: {row.get('profile') or '-'}\n"
            f"Network: {row.get('network') or '-'}\n"
            f"Account: {row.get('account_name') or '-'}\n"
            f"Address: {row.get('address') or '-'}\n"
            f"Tx Hash: {row.get('tx_hash') or '-'}\n"
            f"Created: {row.get('created_at') or '-'}\n"
            f"Details:\n{details_text}"
        )

    def render_balance_snapshot(self, snapshot: dict[str, Any]) -> str:
        if snapshot["status"] != "ok":
            return (
                f"[b]{snapshot['summary']}[/b]\n"
                f"Profile: {snapshot['profile']}\n"
                f"Account: {snapshot.get('account_name') or '-'}\n"
                f"Network: {snapshot.get('network_name') or '-'}\n"
                f"{snapshot['message']}"
            )
        raw_value = snapshot.get("balance_wei") or snapshot.get("balance_raw")
        return (
            f"[b]{snapshot['balance']} {snapshot['symbol']}[/b]\n"
            f"Profile: {snapshot['profile']}\n"
            f"Account: {snapshot['account_name']}\n"
            f"Network: {snapshot['network']}\n"
            f"Address: {snapshot['address']}\n"
            f"Asset Type: {snapshot['asset_type']}\n"
            f"Raw: {raw_value}"
        )

    def render_lookup_result_placeholder(self) -> str:
        return "[b]No lookup loaded[/b]\nRun an address, token, or contract lookup to inspect the target."

    def render_lookup_result(self, payload: dict[str, Any]) -> str:
        details = dict(payload)
        summary = details.pop("summary", "Lookup result")
        return f"[b]{summary}[/b]\n{pretty_json(details)}"

    def render_contract_preview(self, preview: dict[str, Any]) -> str:
        if preview["requires_strong_confirmation"]:
            confirmation = (
                f"[b][yellow]Protected write[/yellow][/b]\n"
                f"Type suffix: {preview['to_address'][-6:]}\n"
                f"Retype value: {preview.get('value') or '0'}\n\n"
            )
        else:
            confirmation = "[b][green]Standard write[/green][/b]\nType YES to execute.\n\n"
        return (
            f"{confirmation}"
            f"[b]{preview.get('contract_function') or 'contract_write'}[/b]\n"
            f"Profile: {preview['profile']}\n"
            f"From: {preview['account_name']} · {preview['from_address']}\n"
            f"To: {preview['to_address']}\n"
            f"Network: {preview['network_name']} ({preview['chain_id']})\n"
            f"Query: {preview.get('query')} ({preview.get('query_kind')})\n"
            f"Args: {pretty_json(preview.get('args') or [])}\n"
            f"Value: {preview.get('value') or '0'}\n"
            f"Gas Limit: {preview['gas_limit']}\n"
            f"Fee Model: {preview['fee_model']}\n"
            f"Max Fee Cost: {preview['max_fee_cost_wei']} wei\n"
            f"Estimated Total: {preview['estimated_total_cost_wei']} wei"
        )

    def render_contract_preview_placeholder(self) -> str:
        return "[b]No contract preview loaded[/b]\nRead, preview, simulate, or execute contract actions from this panel."

    def render_contract_result(self, payload: dict[str, Any]) -> str:
        details = dict(payload)
        summary = details.pop("summary", "Contract result")
        return f"[b]{summary}[/b]\n{pretty_json(details)}"

    def render_contract_result_placeholder(self) -> str:
        return "[b]No contract result loaded[/b]\nContract reads, simulations, and execution results will appear here."

    def render_send_preview(self, preview: dict[str, Any]) -> str:
        recipient = preview["to_address"]
        if preview.get("recipient_name"):
            recipient = f"{recipient} ({preview['recipient_name']})"
        asset = preview["token_address"] if preview["asset_type"] == "erc20" else preview["symbol"]
        if preview["requires_strong_confirmation"]:
            confirmation = f"[b][yellow]Protected send[/yellow][/b]\nType suffix: {preview['to_address'][-6:]}\nRetype amount: {preview['amount']}\n\n"
        else:
            confirmation = "[b][green]Standard send[/green][/b]\nType YES to broadcast.\n\n"
        return (
            f"{confirmation}"
            f"[b]{preview['amount']} {asset}[/b]\n"
            f"Profile: {preview['profile']}\n"
            f"From: {preview['account_name']} · {preview['from_address']}\n"
            f"To: {recipient}\n"
            f"Network: {preview['network_name']} ({preview['chain_id']})\n"
            f"Nonce: {preview['nonce']}\n"
            f"Gas Limit: {preview['gas_limit']}\n"
            f"Fee Model: {preview['fee_model']}\n"
            f"Max Fee Cost: {preview['max_fee_cost_wei']} wei\n"
            f"Estimated Total: {preview['estimated_total_cost_wei']} wei"
        )

    def render_send_preview_placeholder(self) -> str:
        return "[b]No preview loaded[/b]\nFill out the send form, then preview the transaction before broadcasting."

    def render_send_result(self, payload: dict[str, Any]) -> str:
        recipient = payload["to_address"]
        if payload.get("recipient_name"):
            recipient = f"{recipient} ({payload['recipient_name']})"
        return (
            f"[b]Submitted[/b]\n"
            f"Tx Hash: {payload['transaction_hash']}\n"
            f"From: {payload['account_name']} · {payload['from_address']}\n"
            f"To: {recipient}\n"
            f"Network: {payload['network']}\n"
            f"Amount: {payload['amount']} {payload['symbol']}"
        )

    def render_send_result_placeholder(self) -> str:
        return "[b]No transaction submitted[/b]\nBroadcast results will appear here after a successful send."

    def render_policy_placeholder(self) -> str:
        return "[b]No policy loaded[/b]\nLoad the effective policy for this profile or account scope."

    def render_policy_explain_placeholder(self) -> str:
        return "[b]No evaluation loaded[/b]\nExplain a candidate action to see allow or deny results."

    def render_policy_view(self, payload: dict[str, Any]) -> str:
        return f"[b]{payload['scope']} policy[/b]\n{pretty_json(payload['policy'])}"

    def render_policy_explain(self, payload: dict[str, Any]) -> str:
        return (
            f"[b]{'Allowed' if payload['allowed'] else 'Blocked'}[/b]\n"
            f"Account: {payload['account_name']}\n"
            f"Network: {payload['network_name']}\n"
            f"Recipient: {payload['recipient_name']} · {payload['recipient_address']}\n"
            f"Amount: {payload['amount']}\n"
            f"Requires Simulation: {yes_no(payload['requires_simulation'])}\n"
            f"Findings:\n- " + "\n- ".join(payload["findings"])
        )

    def render_receipt_detail(self, payload: dict[str, Any]) -> str:
        return (
            f"[b]Receipt[/b]\n"
            f"Tx Hash: {payload['transaction_hash']}\n"
            f"Network: {payload.get('network') or '-'}\n"
            f"Block: {payload.get('block_number')}\n"
            f"Status: {payload.get('status')}\n"
            f"Gas Used: {payload.get('gas_used')}\n"
            f"Effective Gas Price: {payload.get('effective_gas_price')}"
        )

    def render_monitor_state_placeholder(self) -> str:
        return "[b]No monitor state loaded[/b]\nPoll or start monitoring to capture account activity."

    def render_monitor_state(self, payload: dict[str, Any]) -> str:
        state = payload.get("state", payload)
        return (
            f"[b]{payload['account_name']} @ {payload['network']}[/b]\n"
            f"Address: {payload['address']}\n"
            f"Last Poll: {state.get('last_poll_at') or '-'}\n"
            f"Last Block: {state.get('last_processed_block')}\n"
            f"Last Nonce: {state.get('last_known_nonce')}\n"
            f"Native Balance Wei: {state.get('last_native_balance') or '-'}\n"
            f"Observed Tx Cache: {len(state.get('observed_tx_hashes') or [])}\n"
            f"Settled Tx Cache: {len(state.get('settled_tx_hashes') or [])}"
        )

    def render_monitor_events(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "[b]No observed events[/b]\nNew monitor-written events will appear here."
        lines = []
        for row in rows:
            lines.append(
                f"- {row.get('event_type')} · {row.get('status') or '-'} · {row.get('network') or '-'} · {shorten_hash(row['id'])}"
            )
        return "\n".join(lines)


def shorten_address(address: str) -> str:
    if len(address) <= 14:
        return address
    return f"{address[:8]}…{address[-6:]}"


def shorten_hash(value: str) -> str:
    if len(value) <= 18:
        return value
    return f"{value[:10]}…{value[-8:]}"


def pretty_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def first_journal_id(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    return rows[0]["id"]


def int_or_none(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    return int(stripped)


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def run_tui(home: str | None = None, profile: str | None = None, allow_prod: bool = False) -> None:
    VaultTUI(home=home, profile=profile, allow_prod=allow_prod).run()


SEND_INPUT_IDS = {
    "send_account",
    "send_network",
    "send_to",
    "send_amount",
    "send_token",
    "send_gas_price",
    "send_max_fee",
    "send_priority_fee",
}

CONTRACT_INPUT_IDS = {
    "contract_target",
    "contract_from_account",
    "contract_network",
    "contract_abi_file",
    "contract_abi_fragment",
    "contract_function",
    "contract_args",
    "contract_value",
    "contract_gas_price",
    "contract_max_fee",
    "contract_priority_fee",
}


def preview_fingerprint(preview: dict[str, Any]) -> tuple[str, ...]:
    return (
        preview["profile"],
        preview["account_name"],
        preview["network_name"],
        preview["to_address"],
        preview["asset_type"],
        preview.get("token_address") or "",
        preview.get("contract_function") or "",
        json.dumps(preview.get("args") or [], sort_keys=True),
        preview.get("amount") or "",
        preview.get("value") or "",
        str(preview["nonce"]),
        str(preview["gas_limit"]),
        preview["fee_model"],
        preview["max_fee_cost_wei"],
        preview["estimated_total_cost_wei"],
    )
