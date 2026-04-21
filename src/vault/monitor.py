from __future__ import annotations

from typing import Any

from vault.config import VaultPaths, load_json, save_json


class MonitorStateManager:
    def __init__(self, paths: VaultPaths) -> None:
        self.paths = paths

    def get_state(self, account_name: str, network_name: str) -> dict[str, Any] | None:
        return self._load()["states"].get(self._key(account_name, network_name))

    def save_state(self, account_name: str, network_name: str, state: dict[str, Any]) -> dict[str, Any]:
        store = self._load()
        key = self._key(account_name, network_name)
        store["states"][key] = {
            "account_name": account_name,
            "network_name": network_name,
            **state,
        }
        save_json(self.paths.monitor_state_file, store)
        return store["states"][key]

    def _load(self) -> dict[str, Any]:
        store = load_json(self.paths.monitor_state_file, {"states": {}})
        store.setdefault("states", {})
        return store

    def _key(self, account_name: str, network_name: str) -> str:
        return f"{account_name}:{network_name}"
