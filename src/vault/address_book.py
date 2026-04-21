from __future__ import annotations

from typing import Any

from vault.config import NotFoundError, ValidationError, VaultPaths, load_json, save_json
from vault.keystore import validate_name


def normalize_address(address: str) -> str:
    normalized = address.strip()
    if not normalized.startswith("0x") or len(normalized) != 42:
        raise ValidationError("Address must be a 20-byte hex string starting with 0x.")
    try:
        int(normalized[2:], 16)
    except ValueError as exc:
        raise ValidationError("Address must be valid hexadecimal.") from exc
    return normalized


class AddressBookManager:
    def __init__(self, paths: VaultPaths) -> None:
        self.paths = paths

    def list_entries(self) -> dict[str, Any]:
        payload = self._load_entries()
        rows = sorted(payload["entries"].values(), key=lambda item: item["name"])
        noun = "entry" if len(rows) == 1 else "entries"
        return {
            "summary": f"Found {len(rows)} address book {noun}",
            "entries": rows,
            "count": len(rows),
        }

    def add_entry(
        self,
        name: str,
        address: str,
        network_scope: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        normalized_name = validate_name(name)
        normalized_address = normalize_address(address)
        normalized_network_scope = self._normalize_network_scope(network_scope)
        payload = self._load_entries()
        payload["entries"][normalized_name] = {
            "name": normalized_name,
            "address": normalized_address,
            "network_scope": normalized_network_scope,
            "notes": (notes or "").strip() or None,
        }
        save_json(self.paths.address_book_file, payload)
        return {
            "summary": f"Stored address book entry {normalized_name}",
            **payload["entries"][normalized_name],
        }

    def remove_entry(self, name: str) -> dict[str, Any]:
        normalized_name = validate_name(name)
        payload = self._load_entries()
        removed = payload["entries"].pop(normalized_name, None)
        if not removed:
            raise NotFoundError(f"Address book entry `{normalized_name}` was not found.")
        save_json(self.paths.address_book_file, payload)
        return {
            "summary": f"Removed address book entry {normalized_name}",
            "name": normalized_name,
        }

    def resolve(self, name_or_address: str, network_name: str | None = None) -> dict[str, Any]:
        candidate = name_or_address.strip()
        if candidate.startswith("0x"):
            return {
                "name": None,
                "address": normalize_address(candidate),
                "network_scope": "any",
                "notes": None,
            }

        normalized_name = validate_name(candidate)
        payload = self._load_entries()
        entry = payload["entries"].get(normalized_name)
        if not entry:
            raise NotFoundError(f"Address book entry `{normalized_name}` was not found.")
        if entry["network_scope"] not in ("any", network_name):
            raise ValidationError(
                f"Address book entry `{normalized_name}` is scoped to `{entry['network_scope']}`."
            )
        return entry

    def _load_entries(self) -> dict[str, Any]:
        return load_json(self.paths.address_book_file, {"entries": {}})

    def _normalize_network_scope(self, network_scope: str | None) -> str:
        if not network_scope:
            return "any"
        normalized = network_scope.strip().lower()
        if not normalized:
            return "any"
        return validate_name(normalized)
