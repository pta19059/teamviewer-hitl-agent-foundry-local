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
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

_READ_CONTRACTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "tv_get_account": (frozenset(), frozenset()),
    "tv_get_company": (frozenset(), frozenset()),
    "tv_get_company_license": (frozenset(), frozenset()),
    "tv_list_device_groups": (
        frozenset({"name", "shared", "shouldMatchFullName"}),
        frozenset(),
    ),
    "tv_get_device_group": (frozenset({"group_id"}), frozenset({"group_id"})),
    "tv_list_devices": (
        frozenset({"groupid", "online_state", "full_list"}),
        frozenset(),
    ),
    "tv_get_device": (frozenset({"device_id"}), frozenset({"device_id"})),
    "tv_get_event_logs": (
        frozenset(
            {
                "start_date",
                "end_date",
                "event_names",
                "event_types",
                "account_emails",
                "affected_item",
                "rc_session_guid",
            }
        ),
        frozenset({"start_date", "end_date"}),
    ),
    "tv_list_managed_devices": (frozenset(), frozenset()),
    "tv_list_company_managed_devices": (frozenset(), frozenset()),
    "tv_get_managed_device": (
        frozenset({"device_id"}),
        frozenset({"device_id"}),
    ),
    "tv_get_managed_device_groups": (
        frozenset({"device_id"}),
        frozenset({"device_id"}),
    ),
    "tv_list_managed_groups": (
        frozenset({"limit", "offset"}),
        frozenset(),
    ),
    "tv_list_monitoring_alarms": (
        frozenset({"status", "device_id", "group_id", "start_date", "end_date"}),
        frozenset(),
    ),
    "tv_list_monitoring_devices": (frozenset(), frozenset()),
    "tv_get_device_hardware_info": (
        frozenset({"device_id"}),
        frozenset({"device_id"}),
    ),
    "tv_get_device_system_info": (
        frozenset({"device_id"}),
        frozenset({"device_id"}),
    ),
    "tv_get_device_software_info": (
        frozenset({"device_id"}),
        frozenset({"device_id"}),
    ),
    "tv_list_connection_reports": (
        frozenset(
            {"userid", "groupid", "deviceid", "from_date", "to_date", "limit", "offset"}
        ),
        frozenset(),
    ),
    "tv_get_connection_report": (
        frozenset({"connection_id"}),
        frozenset({"connection_id"}),
    ),
    "tv_get_connection_ai_summary": (
        frozenset({"connection_id"}),
        frozenset({"connection_id"}),
    ),
    "tv_list_device_reports": (
        frozenset({"from_date", "to_date"}),
        frozenset(),
    ),
    "tv_list_sessions": (
        frozenset({"state", "tag"}),
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
        frozenset(
            {
                "description",
                "tag",
                "notes",
                "supporter_name",
                "end_customer_name",
                "end_customer_email",
            }
        ),
        frozenset({"description"}),
    ),
    "tv_update_session": (
        frozenset({"session_code", "description", "tag", "notes"}),
        frozenset({"session_code"}),
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
        frozenset(
            {
                "teamviewer_id",
                "monitoring_policy_id",
                "patch_management_policy_id",
            }
        ),
        frozenset({"teamviewer_id"}),
    ),
    "tv_update_connection_report": (
        frozenset({"connection_id", "notes"}),
        frozenset({"connection_id", "notes"}),
    ),
}

_IDENTIFIER_LABELS: dict[str, re.Pattern[str]] = {
    "sessioncode": re.compile(r"\bsession\s+code\b", re.IGNORECASE),
    "connectionid": re.compile(
        r"\bconnection(?:\s+report)?\s+id\b", re.IGNORECASE
    ),
    "deviceid": re.compile(
        r"\b(?:managed\s+|monitored\s+)?device\s+id\b", re.IGNORECASE
    ),
    "groupid": re.compile(r"\b(?:managed\s+)?group\s+id\b", re.IGNORECASE),
    "teamviewerid": re.compile(r"\bteamviewer\s+id\b", re.IGNORECASE),
    "monitoringpolicyid": re.compile(
        r"\bmonitoring\s+policy\s+id\b", re.IGNORECASE
    ),
    "patchmanagementpolicyid": re.compile(
        r"\bpatch(?:\s+management)?\s+policy\s+id\b", re.IGNORECASE
    ),
    "userid": re.compile(r"\buser\s+id\b", re.IGNORECASE),
    "rcsessionguid": re.compile(
        r"\b(?:remote\s+control|rc)\s+session\s+guid\b", re.IGNORECASE
    ),
}


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


def _contains_exact(prompt: str, value: Any) -> bool:
    needle = str(value).strip()
    if not needle:
        return False
    return (
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])",
            prompt,
            re.IGNORECASE,
        )
        is not None
    )


def _has_labeled_identifier(prompt: str, key: str, value: Any) -> bool:
    label = _IDENTIFIER_LABELS.get(_normalized_key(key))
    if label is None or not _contains_exact(prompt, value):
        return False
    for match in label.finditer(prompt):
        tail = prompt[match.end() : match.end() + 80]
        if _contains_exact(tail, value):
            return True
    return False


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


def _validate_identifier_provenance(
    prompt: str, arguments: Mapping[str, Any]
) -> str | None:
    for key, value in arguments.items():
        if _normalized_key(key) not in _IDENTIFIER_LABELS:
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
    for key in ("pagination_token", "continuation_token"):
        if key in arguments:
            return f"{key} is controlled by the host and cannot be model-supplied."

    for key, value in arguments.items():
        if key in {"start_date", "end_date", "from_date", "to_date"}:
            if _iso_datetime(value) is None:
                return f"{key} must be an ISO 8601 date/time."
            if not _contains_exact(prompt, value):
                return f"{key} must appear exactly in the current request."
        elif key in {"limit", "offset"}:
            if not isinstance(value, int) or isinstance(value, bool):
                return f"{key} must be an integer."
            if key == "limit" and not 1 <= value <= 1000:
                return "limit must be between 1 and 1000."
            if key == "offset" and value < 0:
                return "offset cannot be negative."
            if not _contains_exact(prompt, value):
                return f"{key} must appear exactly in the current request."
        elif key == "online_state":
            if value not in {"Online", "Busy", "NotSupported", "Offline"}:
                return "online_state is not an allowed TeamViewer state."
            if not _contains_exact(prompt, value):
                return "online_state must appear exactly in the current request."
        elif key == "state":
            if value not in {"open", "closed"}:
                return "Session state must be open or closed."
            if not _contains_exact(prompt, value):
                return "Session state must appear exactly in the current request."
        elif key == "status":
            if (
                not isinstance(value, str)
                or not value.strip()
                or not _contains_exact(prompt, value)
            ):
                return "Monitoring alarm status must appear exactly in the current request."
        elif key in {"shared", "shouldMatchFullName", "full_list"}:
            if not isinstance(value, bool):
                return f"{key} must be a boolean."
            if value and key == "shared" and "shared" not in prompt.casefold():
                return "The shared filter was not requested."
            if value and key == "shouldMatchFullName" and not re.search(
                r"\bexact(?:ly)?\b", prompt, re.IGNORECASE
            ):
                return "Exact full-name matching was not requested."
            if value and key == "full_list" and not re.search(
                r"\binclud(?:e|ing)\s+deleted\b", prompt, re.IGNORECASE
            ):
                return "Including deleted devices was not requested."
        elif isinstance(value, list):
            if not value or not all(
                isinstance(item, str)
                and item.strip()
                and _contains_exact(prompt, item)
                for item in value
            ):
                return f"Every {key} value must appear exactly in the current request."
        elif isinstance(value, str):
            if not value.strip() or not _contains_exact(prompt, value):
                return f"The {key} value must appear exactly in the current request."
        else:
            return f"The {key} argument has an unsupported type."

    if function_name in {
        "tv_get_managed_device",
        "tv_get_managed_device_groups",
        "tv_get_device_hardware_info",
        "tv_get_device_system_info",
        "tv_get_device_software_info",
    } and not _canonical_uuid(arguments.get("device_id")):
        return "A canonical managed or monitored device UUID is required."
    if (
        function_name == "tv_list_monitoring_alarms"
        and "device_id" in arguments
        and not _canonical_uuid(arguments.get("device_id"))
    ):
        return "A canonical monitored device UUID is required."

    for key in (
        "session_code",
        "connection_id",
        "group_id",
        "groupid",
        "device_id",
        "deviceid",
        "userid",
    ):
        if key in arguments and not _safe_text_identifier(arguments, key):
            return f"A valid {key} is required."
    if "rc_session_guid" in arguments and not _canonical_uuid(
        arguments.get("rc_session_guid")
    ):
        return "rc_session_guid must be a canonical UUID."
    if "account_emails" in arguments and not all(
        _EMAIL.fullmatch(item) is not None for item in arguments["account_emails"]
    ):
        return "Every account_emails value must be a valid email address."

    start = arguments.get("start_date", arguments.get("from_date"))
    end = arguments.get("end_date", arguments.get("to_date"))
    if start is not None and end is not None:
        start_value = _iso_datetime(start)
        end_value = _iso_datetime(end)
        if start_value is not None and end_value is not None:
            try:
                reversed_range = start_value > end_value
            except TypeError:
                return "The date range must use consistent timezone information."
            if reversed_range:
                return "The start date must not be after the end date."

    if function_name == "tv_list_devices_in_group":
        value = arguments.get("group_name")
        if (
            not isinstance(value, str)
            or not value.strip()
            or not _contains_exact(prompt, value)
        ):
            return "The exact group name must appear in the current request."
    return None


def _validate_write_arguments(
    function_name: str, prompt: str, arguments: Mapping[str, Any]
) -> str | None:
    if function_name == "tv_create_session":
        if not _nonempty_string(arguments, "description"):
            return "A non-empty session description is required."
    elif function_name == "tv_update_session":
        if not _safe_text_identifier(arguments, "session_code"):
            return "A valid session code is required."
        if not any(
            _nonempty_string(arguments, key) for key in ("description", "tag", "notes")
        ):
            return "Specify at least one session field to update: description, tag, or notes."
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
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return "A positive numeric TeamViewer ID is required."
        for key in ("monitoring_policy_id", "patch_management_policy_id"):
            if key in arguments and not _safe_text_identifier(arguments, key):
                return f"A valid non-empty {key} is required when supplied."
    elif function_name == "tv_update_connection_report":
        if not _safe_text_identifier(arguments, "connection_id"):
            return "A valid connection report ID is required."
        if not _nonempty_string(arguments, "notes"):
            return "Non-empty connection-report notes are required."

    for key, value in arguments.items():
        if isinstance(value, str):
            if not value.strip():
                return f"The {key} value cannot be blank."
            if len(value) > 1000:
                return f"The {key} value is too long."
            if not _contains_exact(prompt, value):
                return f"The {key} value was not explicitly supplied by the user."
    email = arguments.get("end_customer_email")
    if email is not None and (
        not isinstance(email, str) or _EMAIL.fullmatch(email) is None
    ):
        return "end_customer_email must be a valid email address."
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
