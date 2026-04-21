from __future__ import annotations

from typing import Any

from vault.config import NotFoundError, VaultPaths, load_json, save_json


class JournalManager:
    def __init__(self, paths: VaultPaths) -> None:
        self.paths = paths

    def list_entries(self) -> dict[str, Any]:
        payload = self._load()
        rows = sorted(payload["entries"].values(), key=lambda item: item["created_at"], reverse=True)
        return {
            "summary": f"Found {len(rows)} journal entr{'y' if len(rows) == 1 else 'ies'}",
            "entries": rows,
            "count": len(rows),
        }

    def get_entry(self, tx_hash: str) -> dict[str, Any]:
        normalized = normalize_tx_hash(tx_hash)
        entry = self._load()["entries"].get(normalized)
        if not entry:
            raise NotFoundError(f"Journal entry `{normalized}` was not found.")
        return {
            "summary": f"Journal entry {normalized}",
            **entry,
        }

    def record_submitted_transaction(self, payload: dict[str, Any], simulation: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = normalize_tx_hash(payload["transaction_hash"])
        store = self._load()
        entry = {
            "tx_hash": normalized,
            "action": "send",
            "status": "submitted",
            "profile": payload.get("profile"),
            "network": payload.get("network"),
            "chain_id": payload.get("chain_id"),
            "account_name": payload.get("account_name"),
            "from_address": payload.get("from_address"),
            "to_address": payload.get("to_address"),
            "recipient_name": payload.get("recipient_name"),
            "asset_type": payload.get("asset_type"),
            "symbol": payload.get("symbol"),
            "token_address": payload.get("token_address"),
            "amount": payload.get("amount"),
            "amount_wei": payload.get("amount_wei"),
            "amount_raw": payload.get("amount_raw"),
            "nonce": payload.get("nonce"),
            "gas_limit": payload.get("gas_limit"),
            "fee_model": payload.get("fee_model"),
            "max_fee_cost_wei": payload.get("max_fee_cost_wei"),
            "estimated_total_cost_wei": payload.get("estimated_total_cost_wei"),
            "created_at": payload.get("submitted_at"),
            "simulation": simulation,
            "receipt": None,
        }
        store["entries"][normalized] = entry
        save_json(self.paths.journal_file, store)
        return {
            "summary": f"Recorded journal entry {normalized}",
            **entry,
        }

    def record_event(self, identifier: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_tx_hash(identifier)
        store = self._load()
        entry = {
            "tx_hash": normalized,
            "action": action,
            **payload,
        }
        store["entries"][normalized] = entry
        save_json(self.paths.journal_file, store)
        return {
            "summary": f"Recorded journal entry {normalized}",
            **entry,
        }

    def attach_receipt(self, tx_hash: str, receipt: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_tx_hash(tx_hash)
        store = self._load()
        entry = store["entries"].get(normalized)
        if not entry:
            raise NotFoundError(f"Journal entry `{normalized}` was not found.")
        entry["receipt"] = receipt
        entry["status"] = "confirmed" if receipt.get("status") == 1 else "failed"
        save_json(self.paths.journal_file, store)
        return {
            "summary": f"Attached receipt for {normalized}",
            **entry,
        }

    def _load(self) -> dict[str, Any]:
        return load_json(self.paths.journal_file, {"entries": {}})


def normalize_tx_hash(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized.startswith("0x"):
        normalized = f"0x{normalized}"
    if len(normalized) != 66:
        raise NotFoundError("Transaction hash must be a 32-byte hex string starting with 0x.")
    try:
        int(normalized[2:], 16)
    except ValueError as exc:
        raise NotFoundError("Transaction hash must be valid hexadecimal.") from exc
    return normalized
