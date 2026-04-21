from __future__ import annotations

from typing import Any

from vault.config import ValidationError


DEFAULT_THEME_NAME = "vault"

THEME_PRESETS: dict[str, dict[str, str]] = {
    "vault": {
        "textual_theme": "textual-dark",
        "description": "Vault default dark operator theme.",
    },
    "nord": {
        "textual_theme": "nord",
        "description": "Low-contrast blue-gray dark theme.",
    },
    "gruvbox": {
        "textual_theme": "gruvbox",
        "description": "Warm dark theme with muted contrast.",
    },
    "tokyo": {
        "textual_theme": "tokyo-night",
        "description": "Cool dark theme with sharper accents.",
    },
    "flexoki": {
        "textual_theme": "flexoki",
        "description": "Soft paper-inspired dark theme.",
    },
}


def normalize_theme_name(name: str | None) -> str:
    normalized = (name or DEFAULT_THEME_NAME).strip().lower()
    if normalized not in THEME_PRESETS:
        raise ValidationError(
            f"Unknown theme `{name}`. Valid themes: {', '.join(THEME_PRESETS)}."
        )
    return normalized


def resolve_textual_theme(name: str | None) -> str:
    return THEME_PRESETS[normalize_theme_name(name)]["textual_theme"]


def theme_rows(active_theme: str | None) -> list[dict[str, Any]]:
    current = normalize_theme_name(active_theme)
    rows = []
    for name, payload in THEME_PRESETS.items():
        rows.append(
            {
                "name": name,
                "textual_theme": payload["textual_theme"],
                "description": payload["description"],
                "is_active": name == current,
            }
        )
    return rows


def cycle_theme_name(current: str | None, step: int = 1) -> str:
    names = list(THEME_PRESETS)
    normalized = normalize_theme_name(current)
    index = names.index(normalized)
    return names[(index + step) % len(names)]
