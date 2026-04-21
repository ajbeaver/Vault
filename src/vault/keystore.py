from __future__ import annotations

import base64
import getpass
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vault.config import (
    DependencyError,
    NotFoundError,
    ValidationError,
    VaultPaths,
    ensure_layout,
    load_json,
    save_json,
)


KDF_ITERATIONS = 390000
KEYSTORE_VERSION = 1


def _require_account_module():
    try:
        from eth_account import Account
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise DependencyError(
            "Missing dependency: web3 is required. Run `pip install -e .`."
        ) from exc
    return Account


def _require_crypto_modules():
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError as exc:  # pragma: no cover - exercised at runtime
        raise DependencyError(
            "Missing dependency: cryptography is required. Run `pip install -e .`."
        ) from exc
    return hashes, AESGCM, PBKDF2HMAC


@dataclass(frozen=True)
class UnlockedAccount:
    name: str
    address: str
    private_key_hex: str


class KeystoreManager:
    def __init__(self, paths: VaultPaths) -> None:
        self.paths = paths
        ensure_layout(paths)

    def create_account(self, name: str, passphrase: str, set_default: bool = False) -> dict[str, Any]:
        account_module = _require_account_module()
        account = account_module.create(os.urandom(32))
        return self._store_account(
            name=name,
            passphrase=passphrase,
            private_key_hex=account.key.hex(),
            address=account.address,
            source="created",
            account_kind="local",
            set_default=set_default,
        )

    def import_account(
        self,
        name: str,
        private_key_hex: str,
        passphrase: str,
        set_default: bool = False,
    ) -> dict[str, Any]:
        account_module = _require_account_module()
        normalized_key = normalize_private_key(private_key_hex)
        account = account_module.from_key(normalized_key)
        return self._store_account(
            name=name,
            passphrase=passphrase,
            private_key_hex=normalized_key,
            address=account.address,
            source="imported",
            account_kind="local",
            set_default=set_default,
        )

    def add_watch_only_account(self, name: str, address: str, set_default: bool = False) -> dict[str, Any]:
        normalized_name = validate_name(name)
        normalized_address = normalize_account_address(address)
        return self._store_watch_only_account(
            name=normalized_name,
            address=normalized_address,
            set_default=set_default,
        )

    def list_accounts(self) -> dict[str, Any]:
        ensure_layout(self.paths)
        config = load_json(self.paths.config_file, {})
        default_account = config.get("default_account")
        rows = []
        for file_path in sorted(self.paths.accounts_dir.glob("*.json")):
            payload = load_json(file_path, {})
            rows.append(
                {
                    "name": payload.get("name"),
                    "address": payload.get("address"),
                    "created_at": payload.get("created_at"),
                    "source": payload.get("source"),
                    "account_kind": payload.get("account_kind", "local"),
                    "signer_type": payload.get("signer_type", "local"),
                    "can_sign": payload.get("can_sign", True),
                    "is_default": payload.get("name") == default_account,
                }
            )
        return {
            "summary": f"Found {len(rows)} account(s)",
            "accounts": rows,
            "count": len(rows),
            "default_account": default_account,
        }

    def unlock_account(self, name: str, passphrase: str) -> UnlockedAccount:
        payload = self._load_account_file(name)
        if payload.get("account_kind") == "watch_only":
            raise ValidationError(f"Account `{payload['name']}` is watch-only and cannot be unlocked.")
        private_key_hex = self._decrypt_private_key(payload, passphrase)
        return UnlockedAccount(
            name=payload["name"],
            address=payload["address"],
            private_key_hex=private_key_hex,
        )

    def get_account_metadata(self, name: str) -> dict[str, Any]:
        payload = self._load_account_file(name)
        return {
            "name": payload["name"],
            "address": payload["address"],
            "created_at": payload.get("created_at"),
            "source": payload.get("source"),
            "account_kind": payload.get("account_kind", "local"),
            "signer_type": payload.get("signer_type", "local"),
            "can_sign": payload.get("can_sign", True),
        }

    def has_account(self, name: str) -> bool:
        normalized_name = validate_name(name)
        return (self.paths.accounts_dir / f"{normalized_name}.json").exists()

    def set_default_account(self, name: str) -> dict[str, Any]:
        payload = self._load_account_file(name)
        config = load_json(self.paths.config_file, {})
        config["default_account"] = payload["name"]
        save_json(self.paths.config_file, config)
        return {
            "summary": f"Default account set to {payload['name']}",
            "name": payload["name"],
            "address": payload["address"],
            "default_account": payload["name"],
        }

    def get_default_account_name(self) -> str | None:
        config = load_json(self.paths.config_file, {})
        return config.get("default_account")

    def prompt_passphrase(self, confirm: bool = False) -> str:
        first = getpass.getpass("Passphrase: ")
        if not first:
            raise ValidationError("Passphrase cannot be empty.")
        if not confirm:
            return first
        second = getpass.getpass("Confirm passphrase: ")
        if first != second:
            raise ValidationError("Passphrases do not match.")
        return first

    def prompt_private_key(self) -> str:
        private_key = getpass.getpass("Private key (hex): ")
        if not private_key:
            raise ValidationError("Private key cannot be empty.")
        return private_key

    def _store_account(
        self,
        name: str,
        passphrase: str,
        private_key_hex: str,
        address: str,
        source: str,
        account_kind: str,
        set_default: bool,
    ) -> dict[str, Any]:
        ensure_layout(self.paths)
        normalized_name = validate_name(name)
        path = self.paths.accounts_dir / f"{normalized_name}.json"
        if path.exists():
            raise ValidationError(f"Account `{normalized_name}` already exists.")

        payload = {
            "version": KEYSTORE_VERSION,
            "name": normalized_name,
            "address": address,
            "source": source,
            "created_at": now_iso(),
            "account_kind": account_kind,
            "signer_type": "local",
            "can_sign": True,
        }
        payload.update(self._encrypt_private_key(private_key_hex, passphrase, normalized_name, address))
        save_json(path, payload)

        config = load_json(self.paths.config_file, {})
        if set_default or not config.get("default_account"):
            config["default_account"] = normalized_name
            save_json(self.paths.config_file, config)

        return {
            "summary": f"Stored account {normalized_name}",
            "name": normalized_name,
            "address": address,
            "source": source,
            "account_kind": account_kind,
            "signer_type": "local",
            "can_sign": True,
            "default_account": config.get("default_account", normalized_name),
        }

    def _store_watch_only_account(
        self,
        name: str,
        address: str,
        set_default: bool,
    ) -> dict[str, Any]:
        ensure_layout(self.paths)
        path = self.paths.accounts_dir / f"{name}.json"
        if path.exists():
            raise ValidationError(f"Account `{name}` already exists.")
        payload = {
            "version": KEYSTORE_VERSION,
            "name": name,
            "address": address,
            "source": "watch_only",
            "created_at": now_iso(),
            "account_kind": "watch_only",
            "signer_type": "watch_only",
            "can_sign": False,
        }
        save_json(path, payload)
        config = load_json(self.paths.config_file, {})
        if set_default or not config.get("default_account"):
            config["default_account"] = name
            save_json(self.paths.config_file, config)
        return {
            "summary": f"Stored watch-only account {name}",
            "name": name,
            "address": address,
            "source": "watch_only",
            "account_kind": "watch_only",
            "signer_type": "watch_only",
            "can_sign": False,
            "default_account": config.get("default_account", name),
        }

    def _load_account_file(self, name: str) -> dict[str, Any]:
        normalized_name = validate_name(name)
        path = self._account_path(normalized_name)
        if not path.exists():
            raise NotFoundError(f"Account `{normalized_name}` was not found.")
        return load_json(path, {})

    def _account_path(self, normalized_name: str) -> Path:
        return self.paths.accounts_dir / f"{normalized_name}.json"

    def _encrypt_private_key(
        self,
        private_key_hex: str,
        passphrase: str,
        name: str,
        address: str,
    ) -> dict[str, str | int]:
        hashes, aesgcm_cls, pbkdf2hmac_cls = _require_crypto_modules()
        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = derive_key(passphrase, salt, hashes, pbkdf2hmac_cls)
        aad = f"{KEYSTORE_VERSION}:{name}:{address}".encode("utf-8")
        ciphertext = aesgcm_cls(key).encrypt(nonce, bytes.fromhex(normalize_private_key(private_key_hex)), aad)
        return {
            "crypto": {
                "cipher": "AES-256-GCM",
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "kdf": "PBKDF2-HMAC-SHA256",
                "iterations": KDF_ITERATIONS,
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "salt": base64.b64encode(salt).decode("ascii"),
            }
        }

    def _decrypt_private_key(self, payload: dict[str, Any], passphrase: str) -> str:
        hashes, aesgcm_cls, pbkdf2hmac_cls = _require_crypto_modules()
        crypto = payload.get("crypto") or {}
        salt = base64.b64decode(crypto["salt"])
        nonce = base64.b64decode(crypto["nonce"])
        ciphertext = base64.b64decode(crypto["ciphertext"])
        aad = f"{payload['version']}:{payload['name']}:{payload['address']}".encode("utf-8")
        key = derive_key(passphrase, salt, hashes, pbkdf2hmac_cls)
        try:
            plaintext = aesgcm_cls(key).decrypt(nonce, ciphertext, aad)
        except Exception as exc:  # pragma: no cover - backend-specific exception
            raise ValidationError("Failed to unlock account. Check the passphrase.") from exc
        return plaintext.hex()


def copy_account_file(source_paths: VaultPaths, target_paths: VaultPaths, name: str, overwrite: bool = False) -> dict[str, Any]:
    ensure_layout(source_paths)
    ensure_layout(target_paths)
    normalized_name = validate_name(name)
    source_file = source_paths.accounts_dir / f"{normalized_name}.json"
    target_file = target_paths.accounts_dir / f"{normalized_name}.json"
    if not source_file.exists():
        raise NotFoundError(f"Account `{normalized_name}` was not found.")
    if target_file.exists() and not overwrite:
        raise ValidationError(f"Account `{normalized_name}` already exists in target profile.")
    shutil.copy2(source_file, target_file)
    payload = load_json(target_file, {})
    return {
        "name": payload["name"],
        "address": payload["address"],
        "source": payload.get("source"),
        "created_at": payload.get("created_at"),
    }


def derive_key(passphrase: str, salt: bytes, hashes_module: Any, pbkdf2hmac_cls: Any) -> bytes:
    kdf = pbkdf2hmac_cls(
        algorithm=hashes_module.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def validate_name(name: str) -> str:
    normalized = name.strip().lower()
    if not normalized:
        raise ValidationError("Name cannot be empty.")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    if any(char not in allowed for char in normalized):
        raise ValidationError("Names may only contain lowercase letters, numbers, `-`, and `_`.")
    return normalized


def normalize_private_key(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("0x"):
        normalized = normalized[2:]
    if len(normalized) != 64:
        raise ValidationError("Private key must contain 32 bytes encoded as 64 hexadecimal characters.")
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise ValidationError("Private key must be valid hexadecimal.") from exc
    return normalized


def normalize_account_address(value: str) -> str:
    normalized = value.strip()
    if not normalized.startswith("0x") or len(normalized) != 42:
        raise ValidationError("Address must be a 20-byte hex string starting with 0x.")
    try:
        int(normalized[2:], 16)
    except ValueError as exc:
        raise ValidationError("Address must be valid hexadecimal.") from exc
    return normalized


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
