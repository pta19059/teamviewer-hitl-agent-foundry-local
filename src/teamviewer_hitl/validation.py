"""Strict pre-execution validation and prompt provenance checks."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from .routing import IntentRoute

_SAFE_TEXT_ID = re.compile(r"^[A-Za-z0-9_-]+$")

_READ_CONTRACTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "tv_get_account": (frozenset(), frozenset()),
    "tv_get_company": (frozenset(), frozenset()),
    "tv_get_company_license": (frozenset(), frozenset()),
    "tv_list_device_groups": (frozenset(), frozenset()),
    "tv_get_device_group": (frozenset({"group_id"}), frozenset({"group_id"})),
    "tv_list_devices": (
        frozenset({"groupid", "online_state"}),
        frozenset(),
    ),
    "tv_get_device": (frozenset({"device_id"}), frozenset({"device_id"})),
    "tv_get_event_logs": (
        frozenset(
            {
                "start_date",
                "end_date",
            }
        ),
        frozenset({"start_date", "end_date"}),
    ),
    "tv_list_managed_devices": (frozenset({"online_state"}), frozenset()),
    "tv_list_company_managed_devices": (
        frozenset({"online_state"}),
        frozenset(),
    ),
    "tv_get_managed_device": (
        frozenset({"device_id"}),
        frozenset({"device_id"}),
    ),
    "tv_get_managed_device_groups": (
        frozenset({"device_id"}),
        frozenset({"device_id"}),
    ),
    "tv_list_managed_groups": (frozenset(), frozenset()),
    "tv_list_monitoring_alarms": (frozenset(), frozenset()),
    "tv_list_monitoring_devices": (frozenset(), frozenset()),
    "tv_get_device_hardware_info": (
        frozenset({"teamviewer_id"}),
        frozenset({"teamviewer_id"}),
    ),
    "tv_get_device_system_info": (
        frozenset({"teamviewer_id"}),
        frozenset({"teamviewer_id"}),
    ),
    "tv_get_device_software_info": (
        frozenset({"teamviewer_id"}),
        frozenset({"teamviewer_id"}),
    ),
    "tv_list_connection_reports": (frozenset(), frozenset()),
    "tv_get_connection_report": (
        frozenset({"connection_id"}),
        frozenset({"connection_id"}),
    ),
    "tv_get_connection_ai_summary": (
        frozenset({"connection_id"}),
        frozenset({"connection_id"}),
    ),
    "tv_list_device_reports": (frozenset(), frozenset()),
    "tv_list_sessions": (
        frozenset({"state"}),
        frozenset(),
    ),
    "tv_get_session": (
        frozenset({"session_code"}),
        frozenset({"session_code"}),
    ),
    "tv_list_devices_in_group": (
        frozenset({"group_name"}),
        frozenset({"group_name"}),
    ),
}

_WRITE_CONTRACTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "tv_create_session": (
        frozenset({"description", "groupid"}),
        frozenset({"description", "groupid"}),
    ),
    "tv_update_session": (
        frozenset({"session_code", "description"}),
        frozenset({"session_code", "description"}),
    ),
    "tv_delete_session": (
        frozenset({"session_code"}),
        frozenset({"session_code"}),
    ),
    "tv_update_managed_device_description": (
        frozenset({"device_id", "description"}),
        frozenset({"device_id", "description"}),
    ),
    "tv_activate_monitoring": (
        frozenset({"teamviewer_id"}),
        frozenset({"teamviewer_id"}),
    ),
    "tv_update_connection_report": (
        frozenset({"connection_id", "notes"}),
        frozenset({"connection_id", "notes"}),
    ),
}

_UUID_TEXT = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_IDENTIFIER_VALUES: dict[str, re.Pattern[str]] = {
    "sessioncode": re.compile(
        r"\bsession\s+code\s+(?P<value>[A-Za-z0-9_-]+)\b", re.IGNORECASE
    ),
    "connectionid": re.compile(
        rf"\bconnection(?:\s+report)?\s+id\s+(?P<value>{_UUID_TEXT})\b",
        re.IGNORECASE,
    ),
    "deviceid": re.compile(
        rf"\b(?:managed\s+|monitored\s+)?device\s+id\s+"
        rf"(?P<value>{_UUID_TEXT}|[A-Za-z0-9_-]+)\b",
        re.IGNORECASE,
    ),
    "groupid": re.compile(
        r"\b(?:managed\s+)?group\s+id\s+(?P<value>[A-Za-z0-9_-]+)\b",
        re.IGNORECASE,
    ),
    "teamviewerid": re.compile(
        r"\bteamviewer\s+id\s+(?P<value>[0-9]+)\b", re.IGNORECASE
    ),
    "monitoringpolicyid": re.compile(
        rf"\bmonitoring\s+policy\s+id\s+(?P<value>{_UUID_TEXT})\b",
        re.IGNORECASE,
    ),
    "patchmanagementpolicyid": re.compile(
        rf"\bpatch(?:\s+management)?\s+policy\s+id\s+(?P<value>{_UUID_TEXT})\b",
        re.IGNORECASE,
    ),
    "userid": re.compile(
        r"\buser\s+id\s+(?P<value>[A-Za-z0-9_-]+)\b", re.IGNORECASE
    ),
    "rcsessionguid": re.compile(
        rf"\b(?:remote\s+control|rc)\s+session\s+guid\s+"
        rf"(?P<value>{_UUID_TEXT})\b",
        re.IGNORECASE,
    ),
}

_ROUTE_BOUND_READ_FIELDS: dict[str, frozenset[str]] = {
    "tv_list_devices": frozenset({"groupid", "online_state"}),
    "tv_list_managed_devices": frozenset({"online_state"}),
    "tv_list_company_managed_devices": frozenset({"online_state"}),
    "tv_list_sessions": frozenset({"state"}),
    "tv_list_devices_in_group": frozenset({"group_name"}),
}
_DATE_RANGE = re.compile(
    r"\bfrom\s+(?P<start>\S+)\s+to\s+(?P<end>\S+)", re.IGNORECASE
)


def arguments_to_dict(arguments: BaseModel | Mapping[str, Any] | str | Any) -> dict[str, Any]:
    if isinstance(arguments, BaseModel):
        return arguments.model_dump(exclude_none=True)
    if isinstance(arguments, Mapping):
        return {key: value for key, value in arguments.items() if value is not None}
    if isinstance(arguments, str):
        import json

        try:
            value = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        if not isinstance(value, Mapping):
            return {}
        return {key: item for key, item in value.items() if item is not None}
    return {}


def _normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())


def _has_labeled_identifier(prompt: str, key: str, value: Any) -> bool:
    selector = _IDENTIFIER_VALUES.get(_normalized_key(key))
    if selector is None:
        return False
    matches = list(selector.finditer(prompt))
    if len(matches) != 1:
        return False
    return str(matches[0].group("value")).casefold() == str(value).casefold()


def _nonempty_string(arguments: Mapping[str, Any], key: str) -> bool:
    value = arguments.get(key)
    return isinstance(value, str) and bool(value.strip())


def _safe_text_identifier(arguments: Mapping[str, Any], key: str) -> bool:
    value = arguments.get(key)
    return isinstance(value, str) and bool(_SAFE_TEXT_ID.fullmatch(value))


def _canonical_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.casefold()
    except ValueError:
        return False


def _iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _validate_contract(
    function_name: str, arguments: Mapping[str, Any]
) -> str | None:
    contract = _READ_CONTRACTS.get(function_name) or _WRITE_CONTRACTS.get(function_name)
    if contract is None:
        return "The routed tool has no application-level argument contract."
    allowed, required = contract
    unknown = set(arguments) - allowed
    if unknown:
        return f"Unsupported argument(s): {', '.join(sorted(unknown))}."
    missing = {
        key
        for key in required
        if key not in arguments
        or arguments[key] is None
        or (isinstance(arguments[key], str) and not arguments[key].strip())
    }
    if missing:
        return f"Missing required argument(s): {', '.join(sorted(missing))}."
    return None


def _comparable_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        normalized = " ".join(value.strip().split())
        if key in {
            "groupid",
            "device_id",
            "connection_id",
            "session_code",
            "state",
            "online_state",
        }:
            return normalized.casefold()
        return normalized
    return value


def _validate_route_binding(
    route: IntentRoute, function_name: str, arguments: Mapping[str, Any]
) -> str | None:
    expected = dict(route.arguments)
    if function_name in _WRITE_CONTRACTS:
        if set(arguments) != set(expected):
            return "The proposed write arguments do not exactly match the routed request."
        for key, value in expected.items():
            if _comparable_value(key, arguments.get(key)) != _comparable_value(key, value):
                return f"The proposed {key} does not match its explicit request field."
        return None

    bound_fields = _ROUTE_BOUND_READ_FIELDS.get(function_name, frozenset())
    for key in bound_fields:
        if key in arguments and key not in expected:
            return f"The {key} filter was not explicitly requested."
    for key, value in expected.items():
        if key not in arguments:
            return f"The explicitly requested {key} filter is missing."
        if _comparable_value(key, arguments[key]) != _comparable_value(key, value):
            return f"The {key} filter does not match the routed request."
    return None


def _validate_identifier_provenance(
    prompt: str, arguments: Mapping[str, Any]
) -> str | None:
    for key, value in arguments.items():
        if _normalized_key(key) not in _IDENTIFIER_VALUES:
            continue
        if not _has_labeled_identifier(prompt, key, value):
            return (
                f"The {key} value must be supplied exactly after its explicit identifier "
                "label in the current request."
            )
    return None


def _validate_read_arguments(
    function_name: str, prompt: str, arguments: Mapping[str, Any]
) -> str | None:
    if function_name == "tv_get_event_logs":
        start = arguments.get("start_date")
        end = arguments.get("end_date")
        if _iso_datetime(start) is None or _iso_datetime(end) is None:
            return "start_date and end_date must be ISO 8601 date/times."
        match = _DATE_RANGE.search(prompt)
        if match is None:
            return "The event-log request must explicitly say 'from <START> to <END>'."
        prompt_start = match.group("start").rstrip(".,")
        prompt_end = match.group("end").rstrip(".,")
        if str(start) != prompt_start or str(end) != prompt_end:
            return "The event-log dates do not match their explicit from/to fields."
        start_value = _iso_datetime(start)
        end_value = _iso_datetime(end)
        assert start_value is not None and end_value is not None
        try:
            if start_value > end_value:
                return "The start date must not be after the end date."
        except TypeError:
            return "The date range must use consistent timezone information."

    if "online_state" in arguments and arguments["online_state"] not in {
        "Online",
        "Offline",
    }:
        return "online_state must be Online or Offline."
    if "state" in arguments and arguments["state"] not in {"open", "closed"}:
        return "Session state must be open or closed."
    monitoring_detail_tools = {
        "tv_get_device_hardware_info",
        "tv_get_device_system_info",
        "tv_get_device_software_info",
    }
    if function_name in monitoring_detail_tools:
        value = arguments.get("teamviewer_id")
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 < value <= 9_007_199_254_740_991
        ):
            return "A positive JavaScript-safe numeric TeamViewer ID is required."

    if function_name in {
        "tv_get_managed_device",
        "tv_get_managed_device_groups",
    } and not _canonical_uuid(arguments.get("device_id")):
        return "A canonical managed-device UUID is required."

    if function_name in {
        "tv_get_connection_report",
        "tv_get_connection_ai_summary",
    } and not _canonical_uuid(arguments.get("connection_id")):
        return "A canonical connection-report UUID is required."

    if function_name == "tv_get_device_group" and re.fullmatch(
        r"g[0-9]+", str(arguments.get("group_id", "")), re.IGNORECASE
    ) is None:
        return "A legacy group ID such as g12345678 is required."
    if function_name == "tv_get_device" and re.fullmatch(
        r"d[0-9]+", str(arguments.get("device_id", "")), re.IGNORECASE
    ) is None:
        return "A legacy device ID such as d12345678 is required."
    if "groupid" in arguments and re.fullmatch(
        r"g[0-9]+", str(arguments["groupid"]), re.IGNORECASE
    ) is None:
        return "groupid must be a legacy group ID such as g12345678."
    if "session_code" in arguments and not _safe_text_identifier(
        arguments, "session_code"
    ):
        return "A valid session code is required."

    if function_name == "tv_list_devices_in_group" and not _nonempty_string(
        arguments, "group_name"
    ):
        return "A non-empty group name is required."
    return None


def _validate_write_arguments(
    function_name: str, prompt: str, arguments: Mapping[str, Any]
) -> str | None:
    if function_name == "tv_create_session":
        if not _nonempty_string(arguments, "description"):
            return "A non-empty session description is required."
        if not _nonempty_string(arguments, "groupid") or re.fullmatch(
            r"g[0-9]+", str(arguments["groupid"]), re.IGNORECASE
        ) is None:
            return "groupid must be a TeamViewer legacy group ID such as g12345678."
    elif function_name == "tv_update_session":
        if not _safe_text_identifier(arguments, "session_code"):
            return "A valid session code is required."
        if not _nonempty_string(arguments, "description"):
            return "A non-empty session description is required."
    elif function_name == "tv_delete_session":
        if not _safe_text_identifier(arguments, "session_code"):
            return "A valid session code is required."
    elif function_name == "tv_update_managed_device_description":
        if not _canonical_uuid(arguments.get("device_id")):
            return "A canonical managed-device UUID is required."
        if not _nonempty_string(arguments, "description"):
            return "A non-empty managed-device description is required."
    elif function_name == "tv_activate_monitoring":
        value = arguments.get("teamviewer_id")
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 < value <= 9_007_199_254_740_991
        ):
            return "A positive JavaScript-safe numeric TeamViewer ID is required."
    elif function_name == "tv_update_connection_report":
        if not _canonical_uuid(arguments.get("connection_id")):
            return "A canonical connection-report UUID is required."
        if not _nonempty_string(arguments, "notes"):
            return "Non-empty connection-report notes are required."

    for key, value in arguments.items():
        if isinstance(value, str):
            if not value.strip():
                return f"The {key} value cannot be blank."
            if len(value) > 1000:
                return f"The {key} value is too long."
    return None


def validate_invocation(
    route: IntentRoute,
    prompt: str,
    function_name: str,
    arguments: Mapping[str, Any],
) -> str | None:
    """Return a blocking explanation, or None when the exact call is safe to attempt."""
    if route.tool_name is None or function_name != route.tool_name:
        return "The model selected a tool that does not match the deterministic route."

    error = _validate_contract(function_name, arguments)
    if error:
        return error
    error = _validate_route_binding(route, function_name, arguments)
    if error:
        return error
    error = _validate_identifier_provenance(prompt, arguments)
    if error:
        return error

    if function_name in _READ_CONTRACTS:
        return _validate_read_arguments(function_name, prompt, arguments)
    if function_name in {
        "tv_assign_monitoring_policy",
        "tv_assign_patch_management_policy",
    }:
        return "Policy assignment is disabled until the upstream MCP schema is fully typed."
    return _validate_write_arguments(function_name, prompt, arguments)
