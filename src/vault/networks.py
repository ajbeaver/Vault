from __future__ import annotations

import os
from typing import Any

from vault.config import NotFoundError, ValidationError, VaultPaths, load_json, save_json
from vault.keystore import validate_name


ALCHEMY_PRESETS: dict[str, dict[str, Any]] = {
    "eth-mainnet": {
        "chain_id": 1,
        "symbol": "ETH",
        "rpc_url_template": "https://eth-mainnet.g.alchemy.com/v2/{api_key}",
    },
    "eth-sepolia": {
        "chain_id": 11155111,
        "symbol": "ETH",
        "rpc_url_template": "https://eth-sepolia.g.alchemy.com/v2/{api_key}",
    },
    "eth-holesky": {
        "chain_id": 17000,
        "symbol": "ETH",
        "rpc_url_template": "https://eth-holesky.g.alchemy.com/v2/{api_key}",
    },
    "base-mainnet": {
        "chain_id": 8453,
        "symbol": "ETH",
        "rpc_url_template": "https://base-mainnet.g.alchemy.com/v2/{api_key}",
    },
    "base-sepolia": {
        "chain_id": 84532,
        "symbol": "ETH",
        "rpc_url_template": "https://base-sepolia.g.alchemy.com/v2/{api_key}",
    },
    "arb-mainnet": {
        "chain_id": 42161,
        "symbol": "ETH",
        "rpc_url_template": "https://arb-mainnet.g.alchemy.com/v2/{api_key}",
    },
    "arb-sepolia": {
        "chain_id": 421614,
        "symbol": "ETH",
        "rpc_url_template": "https://arb-sepolia.g.alchemy.com/v2/{api_key}",
    },
    "opt-mainnet": {
        "chain_id": 10,
        "symbol": "ETH",
        "rpc_url_template": "https://opt-mainnet.g.alchemy.com/v2/{api_key}",
    },
    "opt-sepolia": {
        "chain_id": 11155420,
        "symbol": "ETH",
        "rpc_url_template": "https://opt-sepolia.g.alchemy.com/v2/{api_key}",
    },
    "polygon-mainnet": {
        "chain_id": 137,
        "symbol": "POL",
        "rpc_url_template": "https://polygon-mainnet.g.alchemy.com/v2/{api_key}",
    },
    "polygon-amoy": {
        "chain_id": 80002,
        "symbol": "POL",
        "rpc_url_template": "https://polygon-amoy.g.alchemy.com/v2/{api_key}",
    },
}


class NetworkManager:
    def __init__(self, paths: VaultPaths) -> None:
        self.paths = paths

    def add_network(
        self,
        name: str,
        rpc_url: str,
        chain_id: int,
        symbol: str,
        set_default: bool = False,
    ) -> dict[str, Any]:
        normalized_name = validate_name(name)
        rpc_url = rpc_url.strip()
        symbol = symbol.strip().upper()
        if not rpc_url:
            raise ValidationError("RPC URL cannot be empty.")
        if chain_id <= 0:
            raise ValidationError("Chain ID must be a positive integer.")
        if not symbol:
            raise ValidationError("Symbol cannot be empty.")

        payload = load_json(self.paths.networks_file, {"default_network": None, "networks": {}})
        payload["networks"][normalized_name] = {
            "name": normalized_name,
            "rpc_url": rpc_url,
            "chain_id": chain_id,
            "symbol": symbol,
        }
        if set_default or not payload.get("default_network"):
            payload["default_network"] = normalized_name
        save_json(self.paths.networks_file, payload)
        return self._network_response(payload["networks"][normalized_name], payload["default_network"])

    def add_alchemy_network(
        self,
        preset: str,
        api_key_env: str,
        name: str | None = None,
        set_default: bool = False,
    ) -> dict[str, Any]:
        normalized_preset = preset.strip().lower()
        preset_config = ALCHEMY_PRESETS.get(normalized_preset)
        if not preset_config:
            raise ValidationError(f"Unknown Alchemy preset `{normalized_preset}`.")
        normalized_name = validate_name(name or normalized_preset)
        env_name = validate_env_name(api_key_env)

        payload = load_json(self.paths.networks_file, {"default_network": None, "networks": {}})
        payload["networks"][normalized_name] = {
            "name": normalized_name,
            "provider": "alchemy",
            "alchemy_preset": normalized_preset,
            "api_key_env": env_name,
            "chain_id": preset_config["chain_id"],
            "symbol": preset_config["symbol"],
            "rpc_url_template": preset_config["rpc_url_template"],
        }
        if set_default or not payload.get("default_network"):
            payload["default_network"] = normalized_name
        save_json(self.paths.networks_file, payload)
        return self._network_response(payload["networks"][normalized_name], payload["default_network"])

    def add_anvil_network(
        self,
        name: str = "local",
        rpc_url: str = "http://127.0.0.1:8545",
        chain_id: int = 31337,
        symbol: str = "ETH",
        set_default: bool = False,
    ) -> dict[str, Any]:
        normalized_name = validate_name(name)
        rpc_url = rpc_url.strip()
        symbol = symbol.strip().upper()
        if not rpc_url:
            raise ValidationError("RPC URL cannot be empty.")
        if chain_id <= 0:
            raise ValidationError("Chain ID must be a positive integer.")
        if not symbol:
            raise ValidationError("Symbol cannot be empty.")

        payload = load_json(self.paths.networks_file, {"default_network": None, "networks": {}})
        payload["networks"][normalized_name] = {
            "name": normalized_name,
            "provider": "anvil",
            "rpc_url": rpc_url,
            "chain_id": chain_id,
            "symbol": symbol,
        }
        if set_default or not payload.get("default_network"):
            payload["default_network"] = normalized_name
        save_json(self.paths.networks_file, payload)
        return self._network_response(payload["networks"][normalized_name], payload["default_network"])

    def list_presets(self) -> dict[str, Any]:
        rows = []
        for name, config in sorted(ALCHEMY_PRESETS.items()):
            rows.append(
                {
                    "preset": name,
                    "provider": "alchemy",
                    "chain_id": config["chain_id"],
                    "symbol": config["symbol"],
                    "rpc_url_template": config["rpc_url_template"],
                }
            )
        return {
            "summary": f"Found {len(rows)} Alchemy preset(s)",
            "presets": rows,
            "count": len(rows),
        }

    def list_networks(self) -> dict[str, Any]:
        payload = load_json(self.paths.networks_file, {"default_network": None, "networks": {}})
        default_network = payload.get("default_network")
        rows = []
        for network in sorted(payload["networks"].values(), key=lambda item: item["name"]):
            row = self._display_network(network)
            row["is_default"] = row["name"] == default_network
            rows.append(row)
        return {
            "summary": f"Found {len(rows)} network(s)",
            "default_network": default_network,
            "networks": rows,
            "count": len(rows),
        }

    def set_default_network(self, name: str) -> dict[str, Any]:
        payload = load_json(self.paths.networks_file, {"default_network": None, "networks": {}})
        normalized_name = validate_name(name)
        network = payload["networks"].get(normalized_name)
        if not network:
            raise NotFoundError(f"Network `{normalized_name}` was not found.")
        payload["default_network"] = normalized_name
        save_json(self.paths.networks_file, payload)
        return {
            "summary": f"Default network set to {normalized_name}",
            "name": normalized_name,
            "default_network": normalized_name,
        }

    def get_network(self, name: str | None) -> dict[str, Any]:
        payload = load_json(self.paths.networks_file, {"default_network": None, "networks": {}})
        effective_name = validate_name(name) if name else payload.get("default_network")
        if not effective_name:
            raise ValidationError("No network selected. Use `vault network add-alchemy` or pass `--network`.")
        network = payload["networks"].get(effective_name)
        if not network:
            raise NotFoundError(f"Network `{effective_name}` was not found.")
        return self._resolve_network(network)

    def _resolve_network(self, network: dict[str, Any]) -> dict[str, Any]:
        provider = network.get("provider", "custom")
        resolved = dict(network)
        if provider == "alchemy":
            env_name = network["api_key_env"]
            api_key = os.environ.get(env_name)
            if not api_key:
                raise ValidationError(
                    f"Environment variable `{env_name}` is not set. Export your Alchemy API key first."
                )
            resolved["rpc_url"] = network["rpc_url_template"].format(api_key=api_key)
        return resolved

    def _display_network(self, network: dict[str, Any]) -> dict[str, Any]:
        row = dict(network)
        if row.get("provider") == "alchemy":
            row["rpc_url"] = row.pop("rpc_url_template")
        return row

    def _network_response(self, network: dict[str, Any], default_network: str | None) -> dict[str, Any]:
        payload = self._display_network(network)
        payload["summary"] = f"Stored network {network['name']}"
        payload["default_network"] = default_network
        return payload


def copy_network_record(
    source_paths: VaultPaths,
    target_paths: VaultPaths,
    name: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    payload = load_json(source_paths.networks_file, {"default_network": None, "networks": {}})
    target_payload = load_json(target_paths.networks_file, {"default_network": None, "networks": {}})
    normalized_name = validate_name(name)
    network = payload["networks"].get(normalized_name)
    if not network:
        raise NotFoundError(f"Network `{normalized_name}` was not found.")
    if normalized_name in target_payload["networks"] and not overwrite:
        raise ValidationError(f"Network `{normalized_name}` already exists in target profile.")
    target_payload["networks"][normalized_name] = dict(network)
    save_json(target_paths.networks_file, target_payload)
    row = dict(network)
    if row.get("provider") == "alchemy":
        row["rpc_url"] = row["rpc_url_template"]
    return row


def validate_env_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError("Environment variable name cannot be empty.")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
    if any(char not in allowed for char in normalized):
        raise ValidationError("Environment variable names may only contain letters, numbers, and underscores.")
    return normalized
