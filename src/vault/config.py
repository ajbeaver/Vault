from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_HOME_NAME = ".vault"
DEFAULT_PROFILES = ("dev", "test", "prod")


class VaultError(Exception):
    """Base application error."""


class DependencyError(VaultError):
    """Raised when optional runtime dependencies are missing."""


class ValidationError(VaultError):
    """Raised when user input is invalid."""


class NotFoundError(VaultError):
    """Raised when stored data does not exist."""


@dataclass(frozen=True)
class VaultPaths:
    root_home: Path
    profiles_dir: Path
    state_file: Path
    profile_name: str
    home: Path
    accounts_dir: Path
    config_file: Path
    networks_file: Path
    address_book_file: Path
    journal_file: Path
    policy_file: Path
    smart_accounts_file: Path
    using_legacy_profile_home: bool


def resolve_root_home(home: str | None = None) -> Path:
    return Path(
        home
        or os.environ.get("VAULT_HOME")
        or (Path.home() / DEFAULT_HOME_NAME)
    ).expanduser()


def resolve_paths(home: str | None = None, profile: str | None = None) -> VaultPaths:
    root_home = resolve_root_home(home)
    profile_name = normalize_profile_name(profile or get_active_profile_name(root_home))
    using_legacy_profile_home = use_legacy_profile_home(root_home, profile_name)
    profile_home = root_home if using_legacy_profile_home else (root_home / "profiles" / profile_name)
    return VaultPaths(
        root_home=root_home,
        profiles_dir=root_home / "profiles",
        state_file=root_home / "state.json",
        profile_name=profile_name,
        home=profile_home,
        accounts_dir=profile_home / "accounts",
        config_file=profile_home / "config.json",
        networks_file=profile_home / "networks.json",
        address_book_file=profile_home / "address_book.json",
        journal_file=profile_home / "journal.json",
        policy_file=profile_home / "policy.json",
        smart_accounts_file=profile_home / "smart_accounts.json",
        using_legacy_profile_home=using_legacy_profile_home,
    )


def ensure_layout(paths: VaultPaths) -> None:
    paths.root_home.mkdir(parents=True, exist_ok=True)
    if not paths.using_legacy_profile_home:
        paths.home.mkdir(parents=True, exist_ok=True)
    paths.accounts_dir.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def normalize_profile_name(profile: str) -> str:
    normalized = profile.strip().lower()
    if normalized not in DEFAULT_PROFILES:
        raise ValidationError(
            f"Unknown profile `{profile}`. Valid profiles: {', '.join(DEFAULT_PROFILES)}."
        )
    return normalized


def default_state() -> dict[str, str]:
    return {"active_profile": "prod"}


def get_active_profile_name(root_home: Path) -> str:
    state = load_json(root_home / "state.json", default_state())
    return normalize_profile_name(state.get("active_profile", "prod"))


def set_active_profile_name(root_home: Path, profile: str) -> None:
    normalized = normalize_profile_name(profile)
    save_json(root_home / "state.json", {"active_profile": normalized})


def use_legacy_profile_home(root_home: Path, profile_name: str) -> bool:
    if profile_name != "prod":
        return False
    legacy_markers = (
        root_home / "accounts",
        root_home / "config.json",
        root_home / "networks.json",
        root_home / "address_book.json",
    )
    return any(path.exists() for path in legacy_markers) and not (root_home / "profiles" / "prod").exists()
