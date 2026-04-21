from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from vault.config import ValidationError


def http_get_json(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json"})
    return _read_json(request)


def http_post_json(url: str, payload: Any) -> Any:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Accept": "application/json", "Content-Type": "application/json"})
    return _read_json(request)


def _read_json(request: Request) -> Any:
    try:
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValidationError(f"HTTP error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValidationError(f"HTTP request failed: {exc.reason}") from exc
