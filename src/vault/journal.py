from __future__ import annotations

from typing import Any

from vault.config import NotFoundError, ValidationError, VaultPaths, load_json, save_json


class JournalManager:
    def __init__(self, paths: VaultPaths) -> None:
        self.paths = paths

    def list_entries(self) -> dict[str, Any]:
        store = self._load()
        rows = sorted(store["entries"].values(), key=lambda item: item["created_at"], reverse=True)
        return {
            "summary": f"Found {len(rows)} journal entr{'y' if len(rows) == 1 else 'ies'}",
            "entries": rows,
            "count": len(rows),
        }

    def get_entry(self, entry_id: str) -> dict[str, Any]:
        entry = self._find_entry(entry_id)
        return {
            "summary": f"Journal entry {entry['id']}",
            **entry,
        }

    def record_submitted_transaction(
        self,
        payload: dict[str, Any],
        simulation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tx_hash = normalize_tx_hash(payload["transaction_hash"])
        created_at = payload.get("submitted_at")
        entry = {
            "id": tx_hash,
            "kind": "transaction",
            "origin": "user",
            "event_type": "transaction_submitted",
            "action": payload.get("action", "send"),
            "status": "submitted",
            "profile": payload.get("profile"),
            "network": payload.get("network"),
            "chain_id": payload.get("chain_id"),
            "account_name": payload.get("account_name"),
            "address": payload.get("from_address"),
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
            "created_at": created_at,
            "tx_hash": tx_hash,
            "receipt": None,
            "simulation": simulation,
            "details": payload.get("details"),
        }
        return self._upsert(entry)

    def record_event(self, identifier: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        entry = {
            "id": normalize_event_id(identifier),
            "kind": payload.get("kind", "observation"),
            "origin": payload.get("origin", "system"),
            "event_type": payload.get("event_type", action),
            "action": action,
            "status": payload.get("status"),
            "profile": payload.get("profile"),
            "network": payload.get("network"),
            "chain_id": payload.get("chain_id"),
            "account_name": payload.get("account_name"),
            "address": payload.get("address") or payload.get("from_address"),
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
            "created_at": payload.get("created_at"),
            "tx_hash": normalize_optional_tx_hash(payload.get("tx_hash")),
            "receipt": payload.get("receipt"),
            "simulation": payload.get("simulation"),
            "details": payload.get("details"),
        }
        return self._upsert(entry)

    def attach_receipt(self, entry_id_or_tx_hash: str, receipt: dict[str, Any]) -> dict[str, Any]:
        normalized_tx_hash = normalize_tx_hash(entry_id_or_tx_hash)
        store = self._load()
        entry_key, entry = self._find_entry_record(store, normalized_tx_hash)
        if not entry.get("tx_hash"):
            raise NotFoundError(f"Journal entry `{entry['id']}` is not transaction-backed.")
        entry["receipt"] = receipt
        entry["status"] = "confirmed" if receipt.get("status") == 1 else "failed"
        store["entries"][entry_key] = entry
        save_json(self.paths.journal_file, store)
        return {
            "summary": f"Attached receipt for {entry['tx_hash']}",
            **entry,
        }

    def transaction_entries(self) -> list[dict[str, Any]]:
        return [row for row in self._load()["entries"].values() if row.get("tx_hash")]

    def monitor_entries(
        self,
        account_name: str | None = None,
        network_name: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.list_entries()["entries"]
            if row.get("origin") == "monitor"
            and (account_name is None or row.get("account_name") == account_name)
            and (network_name is None or row.get("network") == network_name)
        ]
        if limit is not None:
            rows = rows[:limit]
        return rows

    def _upsert(self, entry: dict[str, Any]) -> dict[str, Any]:
        if not entry.get("created_at"):
            raise ValidationError("Journal entries require `created_at`.")
        store = self._load()
        store["entries"][entry["id"]] = entry
        save_json(self.paths.journal_file, store)
        return {
            "summary": f"Recorded journal entry {entry['id']}",
            **entry,
        }

    def _find_entry(self, entry_id: str) -> dict[str, Any]:
        _, entry = self._find_entry_record(self._load(), entry_id)
        return entry

    def _find_entry_record(self, store: dict[str, Any], entry_id: str) -> tuple[str, dict[str, Any]]:
        normalized_id = normalize_event_id(entry_id)
        entry = store["entries"].get(normalized_id)
        if entry:
            return normalized_id, entry
        tx_hash = normalize_optional_tx_hash(entry_id)
        if tx_hash:
            for key, row in store["entries"].items():
                if row.get("tx_hash") == tx_hash:
                    return key, row
        raise NotFoundError(f"Journal entry `{entry_id}` was not found.")

    def _load(self) -> dict[str, Any]:
        store = load_json(self.paths.journal_file, {"entries": {}})
        store.setdefault("entries", {})
        for key, row in list(store["entries"].items()):
            normalized = self._normalize_legacy_row(key, row)
            if normalized["id"] != key:
                store["entries"].pop(key, None)
            store["entries"][normalized["id"]] = normalized
        return store

    def _normalize_legacy_row(self, key: str, row: dict[str, Any]) -> dict[str, Any]:
        tx_hash = normalize_optional_tx_hash(row.get("tx_hash") or key)
        entry_id = normalize_event_id(row.get("id") or tx_hash or key)
        return {
            "id": entry_id,
            "kind": row.get("kind", "transaction" if tx_hash else "observation"),
            "origin": row.get("origin", "user" if tx_hash else "system"),
            "event_type": row.get("event_type", row.get("action", "event")),
            "action": row.get("action", "event"),
            "status": row.get("status"),
            "profile": row.get("profile"),
            "network": row.get("network"),
            "chain_id": row.get("chain_id"),
            "account_name": row.get("account_name"),
            "address": row.get("address") or row.get("from_address"),
            "from_address": row.get("from_address"),
            "to_address": row.get("to_address"),
            "recipient_name": row.get("recipient_name"),
            "asset_type": row.get("asset_type"),
            "symbol": row.get("symbol"),
            "token_address": row.get("token_address"),
            "amount": row.get("amount"),
            "amount_wei": row.get("amount_wei"),
            "amount_raw": row.get("amount_raw"),
            "nonce": row.get("nonce"),
            "gas_limit": row.get("gas_limit"),
            "fee_model": row.get("fee_model"),
            "max_fee_cost_wei": row.get("max_fee_cost_wei"),
            "estimated_total_cost_wei": row.get("estimated_total_cost_wei"),
            "created_at": row.get("created_at"),
            "tx_hash": tx_hash,
            "receipt": row.get("receipt"),
            "simulation": row.get("simulation"),
            "details": row.get("details") or row.get("payload"),
        }


def normalize_event_id(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise NotFoundError("Journal event identifier cannot be empty.")
    tx_hash = normalize_optional_tx_hash(stripped)
    if tx_hash:
        return tx_hash
    return stripped.lower()


def normalize_optional_tx_hash(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return normalize_tx_hash(value)
    except NotFoundError:
        return None


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
