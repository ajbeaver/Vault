from __future__ import annotations

from typing import Any

from vault.config import ValidationError, VaultPaths
from vault.evm import EVMClient
from vault.keystore import KeystoreManager


def _require_eth_account():
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct, encode_typed_data
    except ImportError as exc:  # pragma: no cover - runtime dependency path
        raise ValidationError("Missing dependency: web3/eth-account is required. Run `pip install -e .`.") from exc
    return Account, encode_defunct, encode_typed_data


class BaseSigner:
    signer_type = "unknown"
    can_sign = False

    def __init__(self, paths: VaultPaths, metadata: dict[str, Any]) -> None:
        self.paths = paths
        self.metadata = metadata

    @property
    def name(self) -> str:
        return self.metadata["name"]

    @property
    def address(self) -> str:
        return self.metadata["address"]

    def ensure_can_sign(self) -> None:
        if not self.can_sign:
            raise ValidationError(f"Account `{self.name}` is watch-only and cannot sign or broadcast.")

    def sign_message(self, passphrase: str, message: str) -> dict[str, Any]:
        raise ValidationError(f"Signer `{self.signer_type}` does not support message signing yet.")

    def sign_typed_data(self, passphrase: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise ValidationError(f"Signer `{self.signer_type}` does not support typed-data signing yet.")

    def send_prepared(self, passphrase: str, preview: dict[str, Any], network: dict[str, Any]) -> dict[str, Any]:
        raise ValidationError(f"Signer `{self.signer_type}` does not support transaction execution yet.")


class LocalAccountSigner(BaseSigner):
    signer_type = "local"
    can_sign = True

    def __init__(self, paths: VaultPaths, metadata: dict[str, Any]) -> None:
        super().__init__(paths, metadata)
        self.accounts = KeystoreManager(paths)

    def sign_message(self, passphrase: str, message: str) -> dict[str, Any]:
        self.ensure_can_sign()
        account_module, encode_defunct, _ = _require_eth_account()
        unlocked = self.accounts.unlock_account(self.name, passphrase)
        signed = account_module.sign_message(encode_defunct(text=message), unlocked.private_key_hex)
        return {
            "summary": f"Signed message with {self.name}",
            "account_name": self.name,
            "address": self.address,
            "signer_type": self.signer_type,
            "message": message,
            "message_hash": prefixed_hex(signed.message_hash),
            "signature": prefixed_hex(signed.signature),
        }

    def sign_typed_data(self, passphrase: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_can_sign()
        account_module, _, encode_typed_data = _require_eth_account()
        unlocked = self.accounts.unlock_account(self.name, passphrase)
        message = encode_typed_data(full_message=payload)
        signed = account_module.sign_message(message, unlocked.private_key_hex)
        return {
            "summary": f"Signed typed data with {self.name}",
            "account_name": self.name,
            "address": self.address,
            "signer_type": self.signer_type,
            "primary_type": payload.get("primaryType"),
            "domain": payload.get("domain"),
            "message_hash": prefixed_hex(signed.message_hash),
            "signature": prefixed_hex(signed.signature),
        }

    def send_prepared(self, passphrase: str, preview: dict[str, Any], network: dict[str, Any]) -> dict[str, Any]:
        self.ensure_can_sign()
        unlocked = self.accounts.unlock_account(self.name, passphrase)
        return EVMClient(network).send_prepared(preview, unlocked.private_key_hex)


class WatchOnlySigner(BaseSigner):
    signer_type = "watch_only"
    can_sign = False


def resolve_signer(paths: VaultPaths, metadata: dict[str, Any]) -> BaseSigner:
    account_kind = metadata.get("account_kind") or "local"
    if account_kind == "watch_only":
        return WatchOnlySigner(paths, metadata)
    return LocalAccountSigner(paths, metadata)


def prefixed_hex(value: Any) -> str:
    if hasattr(value, "hex"):
        raw = value.hex()
    else:
        raw = str(value)
    return raw if raw.startswith("0x") else f"0x{raw}"
