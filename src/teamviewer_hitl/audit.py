"""Minimal local audit trail for human approval decisions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = {"password", "secret", "token", "authorization", "api_key", "apikey"}


def redact(value: Any) -> Any:
    """Recursively remove common credential fields before writing approval arguments."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def record_decision(
    path: Path,
    *,
    operator_id: str,
    tool_name: str,
    arguments: Any,
    approved: bool,
) -> None:
    """Append a decision record. This records intent, not successful tool completion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operator_id": operator_id,
        "tool": tool_name,
        "arguments": redact(arguments),
        "approved": approved,
        "event": "tool_approval_decision",
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        # ACLs are platform-dependent; deployment should enforce access at the host level.
        pass
