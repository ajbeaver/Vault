from __future__ import annotations

import json
from typing import Any


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(format_human(payload))


def format_human(payload: dict[str, Any]) -> str:
    lines = []
    summary = payload.get("summary")
    if summary:
        lines.append(str(summary))
    for key, value in payload.items():
        if key == "summary":
            continue
        label = key.replace("_", " ").title()
        rendered = render_value(value)
        if should_render_multiline(value, rendered):
            lines.append(f"{label}:")
            lines.append(rendered)
        else:
            lines.append(f"{label}: {rendered}")
    return "\n".join(lines)


def render_value(value: Any) -> str:
    if isinstance(value, dict):
        parts = [f"{key}={render_value(inner)}" for key, inner in sorted(value.items())]
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(isinstance(item, dict) for item in value):
            rows = []
            for item in value:
                parts = [f"{key}={render_value(inner)}" for key, inner in sorted(item.items())]
                rows.append("- " + ", ".join(parts))
            return "\n".join(rows)
        return "[" + ", ".join(render_value(item) for item in value) + "]"
    if value is None:
        return "-"
    return str(value)


def should_render_multiline(value: Any, rendered: str) -> bool:
    return "\n" in rendered or (
        isinstance(value, list) and bool(value) and all(isinstance(item, dict) for item in value)
    )
