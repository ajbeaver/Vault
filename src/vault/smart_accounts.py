from __future__ import annotations

from typing import Any

from vault.address_book import normalize_address
from vault.config import NotFoundError, ValidationError, VaultPaths, load_json, save_json
from vault.keystore import validate_name


SMART_ACCOUNT_TYPES = {"safe", "erc4337"}


class SmartAccountManager:
    def __init__(self, paths: VaultPaths) -> None:
        self.paths = paths

    def list_accounts(self) -> dict[str, Any]:
        payload = self._load()
        default_name = payload.get("default_smart_account")
        rows = []
        for item in sorted(payload["accounts"].values(), key=lambda row: row["name"]):
            row = dict(item)
            row["is_default"] = row["name"] == default_name
            rows.append(row)
        return {
            "summary": f"Found {len(rows)} smart account(s)",
            "accounts": rows,
            "count": len(rows),
            "default_smart_account": default_name,
        }

    def get_account(self, name: str | None) -> dict[str, Any]:
        payload = self._load()
        effective_name = validate_name(name) if name else payload.get("default_smart_account")
        if not effective_name:
            raise ValidationError("No smart account selected.")
        account = payload["accounts"].get(effective_name)
        if not account:
            raise NotFoundError(f"Smart account `{effective_name}` was not found.")
        return dict(account)

    def set_default_account(self, name: str) -> dict[str, Any]:
        payload = self._load()
        normalized = validate_name(name)
        if normalized not in payload["accounts"]:
            raise NotFoundError(f"Smart account `{normalized}` was not found.")
        payload["default_smart_account"] = normalized
        save_json(self.paths.smart_accounts_file, payload)
        return {
            "summary": f"Default smart account set to {normalized}",
            "name": normalized,
            "default_smart_account": normalized,
        }

    def register_safe(
        self,
        name: str,
        address: str,
        network: str,
        owners: list[str],
        threshold: int,
        service_url: str | None = None,
        entrypoint: str | None = None,
        set_default: bool = False,
    ) -> dict[str, Any]:
        normalized_name = validate_name(name)
        payload = self._load()
        payload["accounts"][normalized_name] = {
            "name": normalized_name,
            "type": "safe",
            "address": normalize_address(address),
            "network": validate_name(network),
            "owners": [normalize_address(owner) for owner in owners],
            "threshold": validate_threshold(threshold),
            "service_url": normalize_url(service_url),
            "entrypoint": normalize_optional_address(entrypoint),
        }
        if set_default or not payload.get("default_smart_account"):
            payload["default_smart_account"] = normalized_name
        save_json(self.paths.smart_accounts_file, payload)
        return {
            "summary": f"Stored Safe smart account {normalized_name}",
            **payload["accounts"][normalized_name],
            "default_smart_account": payload.get("default_smart_account"),
        }

    def register_erc4337(
        self,
        name: str,
        sender: str,
        network: str,
        owner_account: str,
        entrypoint: str,
        version: str = "0.6",
        factory: str | None = None,
        factory_data: str | None = None,
        bundler_url: str | None = None,
        paymaster_url: str | None = None,
        set_default: bool = False,
    ) -> dict[str, Any]:
        normalized_name = validate_name(name)
        payload = self._load()
        payload["accounts"][normalized_name] = {
            "name": normalized_name,
            "type": "erc4337",
            "address": normalize_address(sender),
            "network": validate_name(network),
            "owner_account": validate_name(owner_account),
            "entrypoint": normalize_address(entrypoint),
            "version": normalize_version(version),
            "factory": normalize_optional_address(factory),
            "factory_data": normalize_hex_data(factory_data) if factory_data else "0x",
            "bundler_url": normalize_url(bundler_url),
            "paymaster_url": normalize_url(paymaster_url),
            "signature_mode": "userop_hash_v06_eoa" if version == "0.6" else "manual",
        }
        if set_default or not payload.get("default_smart_account"):
            payload["default_smart_account"] = normalized_name
        save_json(self.paths.smart_accounts_file, payload)
        return {
            "summary": f"Stored ERC-4337 smart account {normalized_name}",
            **payload["accounts"][normalized_name],
            "default_smart_account": payload.get("default_smart_account"),
        }

    def remove_account(self, name: str) -> dict[str, Any]:
        payload = self._load()
        normalized = validate_name(name)
        if normalized not in payload["accounts"]:
            raise NotFoundError(f"Smart account `{normalized}` was not found.")
        payload["accounts"].pop(normalized)
        if payload.get("default_smart_account") == normalized:
            payload["default_smart_account"] = None
        save_json(self.paths.smart_accounts_file, payload)
        return {
            "summary": f"Removed smart account {normalized}",
            "name": normalized,
        }

    def update_account(self, name: str, updates: dict[str, Any]) -> dict[str, Any]:
        payload = self._load()
        normalized = validate_name(name)
        account = payload["accounts"].get(normalized)
        if not account:
            raise NotFoundError(f"Smart account `{normalized}` was not found.")
        account.update(updates)
        save_json(self.paths.smart_accounts_file, payload)
        return {
            "summary": f"Updated smart account {normalized}",
            **account,
        }

    def _load(self) -> dict[str, Any]:
        return load_json(self.paths.smart_accounts_file, {"default_smart_account": None, "accounts": {}})


def normalize_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SMART_ACCOUNT_TYPES:
        raise ValidationError(f"Unknown smart account type `{value}`.")
    return normalized


def normalize_optional_address(value: str | None) -> str | None:
    if not value:
        return None
    return normalize_address(value)


def normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized.startswith(("https://", "http://")):
        raise ValidationError("URLs must start with http:// or https://.")
    return normalized


def normalize_hex_data(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized.startswith("0x"):
        raise ValidationError("Hex data must start with 0x.")
    try:
        int(normalized[2:] or "0", 16)
    except ValueError as exc:
        raise ValidationError("Hex data must be valid hexadecimal.") from exc
    return normalized


def normalize_version(value: str) -> str:
    normalized = value.strip()
    if normalized not in {"0.6", "0.7"}:
        raise ValidationError("ERC-4337 version must be one of: 0.6, 0.7.")
    return normalized


def validate_threshold(value: int) -> int:
    if value <= 0:
        raise ValidationError("Threshold must be a positive integer.")
    return value
