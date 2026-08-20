"""Deterministic, fail-closed routing for TeamViewer operator requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .policy import APPROVAL_REQUIRED_TOOLS, READ_ONLY_TOOLS, UNSAFE_DISABLED_TOOLS


class RouteOutcome(str, Enum):
    TOOL = "tool"
    CONVERSATION = "conversation"
    CLARIFY = "clarify"


@dataclass(frozen=True, slots=True)
class IntentRoute:
    outcome: RouteOutcome
    intent: str
    tool_name: str | None = None
    mutating: bool = False
    message: str | None = None


_EXPLICIT_TOOL = re.compile(
    r"\b(?:use|call|invoke)\s+(?:only\s+)?(tv_[a-z0-9_]+)\b", re.IGNORECASE
)
_NEGATED_OPERATION = re.compile(r"\b(?:do\s+not|don't|never)\b", re.IGNORECASE)
_INFORMATIONAL_OPERATION = re.compile(
    r"(?:^\s*how\s+(?:do|would|can|could)\s+i\b|"
    r"\b(?:explain|describe)\b.{0,30}\bhow\b|"
    r"^\s*what\s+would\s+happen\b)",
    re.IGNORECASE,
)
_CREATE = re.compile(r"\bcreate\b", re.IGNORECASE)
_OPEN_OR_START = re.compile(r"\b(?:open|start)\b", re.IGNORECASE)
_UPDATE = re.compile(r"\b(?:update|modify|edit|change|set)\b", re.IGNORECASE)
_ADD_FIELD = re.compile(
    r"(?:\badd\b.{0,60}\b(?:description|notes?|tag)\b|"
    r"\b(?:description|notes?|tag)\b.{0,60}\badd\b)",
    re.IGNORECASE,
)
_DELETE = re.compile(r"\b(?:close|terminate|delete|remove|end)\b", re.IGNORECASE)
_ACTIVATE = re.compile(r"\b(?:activate|enable)\b|\bturn\s+on\b", re.IGNORECASE)
_ASSIGN = re.compile(r"\b(?:assign|apply)\b", re.IGNORECASE)
_MUTATING_VERB = re.compile(
    r"\b(?:create|open|start|add|update|modify|edit|change|set|rename|close|"
    r"terminate|delete|remove|end|activate|enable|disable|assign|apply|acknowledge|"
    r"send|share|unshare|install|push)\b",
    re.IGNORECASE,
)
_STRONG_MUTATING_VERB = re.compile(
    r"\b(?:create|add|update|modify|edit|change|set|rename|close|terminate|delete|"
    r"remove|end|activate|enable|disable|assign|apply|acknowledge|send|share|"
    r"unshare|install|push)\b",
    re.IGNORECASE,
)
_READ_REQUEST = re.compile(
    r"\b(?:list(?:ing)?|show(?:ing)?|get(?:ting)?|find(?:ing)?|display(?:ing)?|"
    r"which|what)\b",
    re.IGNORECASE,
)
_OPERATIONAL_VERB = re.compile(
    r"\b(?:create|open|start|close|terminate|delete|end|update|modify|edit|change|set|"
    r"activate|enable|assign|apply|list|show|get|find)\b",
    re.IGNORECASE,
)
_CREATE_SESSION_GROUP_ID = re.compile(
    r"\b(?:in|for|within)\s+(?:legacy\s+)?group\s+id\s+(?P<groupid>g[0-9]+)\b",
    re.IGNORECASE,
)
_CREATE_SESSION_GROUP_ID_LABEL = re.compile(
    r"\b(?:legacy\s+)?group\s+id\b", re.IGNORECASE
)
_CREATE_SESSION_GROUP_NAME_LABEL = re.compile(
    r"\b(?:legacy\s+)?group\s+name\b", re.IGNORECASE
)
_CREATE_SESSION_GROUP_ID_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])g[0-9]+(?![A-Za-z0-9])", re.IGNORECASE
)
_CREATE_SESSION_DESCRIPTION = re.compile(
    r"\b(?:with\s+description|named)\s+(?P<description>.+?)"
    r"(?=\s+(?:in|for|within)\s+(?:legacy\s+)?group\s+id\s+g[0-9]+\b)",
    re.IGNORECASE,
)
_CREATE_SESSION_DESCRIPTION_LABEL = re.compile(
    r"\b(?:with\s+description|named)\b", re.IGNORECASE
)
_CREATE_SESSION_GROUP_GUIDANCE = (
    "Creating a TeamViewer support session requires exactly one existing legacy Computers & "
    "Contacts selector: 'in group ID <GROUP_ID>'. List device groups first if needed."
)
_CREATE_SESSION_DESCRIPTION_GUIDANCE = (
    "Creating a TeamViewer support session requires exactly one explicit description before "
    "the group selector: 'with description <DESCRIPTION> in group ID <GROUP_ID>'."
)


def _has(pattern: re.Pattern[str], text: str) -> bool:
    return pattern.search(text) is not None


def create_session_group_ids(text: str) -> tuple[str, ...]:
    """Capture every immediate, explicitly labelled create-session group ID."""
    return tuple(
        match.group("groupid") for match in _CREATE_SESSION_GROUP_ID.finditer(text)
    )


def create_session_descriptions(text: str) -> tuple[str, ...]:
    """Capture explicitly labelled descriptions immediately before the group selector."""
    values: list[str] = []
    for match in _CREATE_SESSION_DESCRIPTION.finditer(text):
        value = " ".join(match.group("description").strip().split())
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1].strip()
        values.append(value)
    return tuple(values)


def _has_one_create_session_group_id(text: str) -> bool:
    return (
        len(create_session_group_ids(text)) == 1
        and len(_CREATE_SESSION_GROUP_ID_LABEL.findall(text)) == 1
        and len(_CREATE_SESSION_GROUP_ID_TOKEN.findall(text)) == 1
        and not _has(_CREATE_SESSION_GROUP_NAME_LABEL, text)
    )


def _create_session_prompt_error(text: str) -> str | None:
    if not _has_one_create_session_group_id(text):
        return _CREATE_SESSION_GROUP_GUIDANCE
    if (
        len(create_session_descriptions(text)) != 1
        or len(_CREATE_SESSION_DESCRIPTION_LABEL.findall(text)) != 1
    ):
        return _CREATE_SESSION_DESCRIPTION_GUIDANCE
    return None


def _write_matches(text: str, lowered: str) -> list[tuple[str, str]]:
    """Classify supported writes by action and object, independent of word order."""
    matches: list[tuple[str, str]] = []
    has_session = re.search(r"\bsessions?\b", lowered) is not None
    has_managed_device = re.search(r"\bmanaged[ -]devices?\b", lowered) is not None
    has_connection_report = (
        re.search(r"\bconnection[ -]reports?\b", lowered) is not None
    )
    has_monitoring_policy = (
        re.search(r"\bmonitoring[ -]polic(?:y|ies)\b", lowered) is not None
    )
    has_patch_policy = (
        re.search(r"\bpatch(?:[ -]management)?[ -]polic(?:y|ies)\b", lowered)
        is not None
    )

    has_read_request = _READ_REQUEST.search(text) is not None
    weak_session_create = _has(_OPEN_OR_START, text) and not has_read_request
    starts_monitoring = re.search(
        r"\bstart\b(?!\s+by\b).{0,30}\bmonitoring\b", text, re.IGNORECASE
    ) is not None

    if has_session and (_has(_CREATE, text) or weak_session_create):
        matches.append(("create_session", "tv_create_session"))
    if has_session and (_has(_UPDATE, text) or _has(_ADD_FIELD, text)):
        matches.append(("update_session", "tv_update_session"))
    if has_session and _has(_DELETE, text):
        matches.append(("close_session", "tv_delete_session"))
    if (
        has_managed_device
        and "description" in lowered
        and _has(_UPDATE, text)
    ):
        matches.append(
            (
                "update_managed_device_description",
                "tv_update_managed_device_description",
            )
        )
    if (
        "monitoring" in lowered
        and not has_monitoring_policy
        and (_has(_ACTIVATE, text) or starts_monitoring)
    ):
        matches.append(("activate_monitoring", "tv_activate_monitoring"))
    if has_monitoring_policy and (_has(_ASSIGN, text) or _has(_UPDATE, text)):
        matches.append(("assign_monitoring_policy", "tv_assign_monitoring_policy"))
    if has_patch_policy and (_has(_ASSIGN, text) or _has(_UPDATE, text)):
        matches.append(
            ("assign_patch_policy", "tv_assign_patch_management_policy")
        )
    if has_connection_report and _has(_UPDATE, text):
        matches.append(("update_connection_report", "tv_update_connection_report"))
    return matches


def _has_unsupported_write(text: str, lowered: str) -> bool:
    """Detect state changes that must never fall through to a read route."""
    if _has(_DELETE, text) and any(
        phrase in lowered
        for phrase in (
            "connection report",
            "managed group",
            "device group",
            "managed device",
            "monitoring alarm",
            "monitoring alert",
        )
    ):
        return True
    if re.search(r"\b(?:create|add)\b", text, re.IGNORECASE) and any(
        phrase in lowered
        for phrase in (
            "managed group",
            "device group",
            "managed device",
        )
    ):
        return True
    if _has(_UPDATE, text) and any(
        phrase in lowered
        for phrase in ("managed group", "device group")
    ):
        return True
    if re.search(r"\b(?:acknowledge|disable)\b", text, re.IGNORECASE):
        return True
    return False


def _has_multiple_operations(text: str) -> bool:
    clauses = re.split(r"\s+(?:and\s+then|and|then)\s+|[;]", text, flags=re.IGNORECASE)
    operation = re.compile(
        rf"(?:{_OPERATIONAL_VERB.pattern}|{_MUTATING_VERB.pattern}|"
        r"\b(?:use|call|invoke)\b)",
        re.IGNORECASE,
    )
    return sum(operation.search(clause) is not None for clause in clauses) > 1


def _has_multiple_write_targets(text: str) -> bool:
    labels = (
        r"\bsession\s+code\b",
        r"\bconnection(?:\s+report)?\s+id\b",
        r"\b(?:managed\s+|monitored\s+)?device\s+id\b",
        r"\bteamviewer\s+id\b",
    )
    return any(len(re.findall(label, text, re.IGNORECASE)) > 1 for label in labels)


def _tool_route(intent: str, tool_name: str) -> IntentRoute:
    return IntentRoute(
        outcome=RouteOutcome.TOOL,
        intent=intent,
        tool_name=tool_name,
        mutating=tool_name in APPROVAL_REQUIRED_TOOLS,
    )


def _clarify(message: str) -> IntentRoute:
    return IntentRoute(RouteOutcome.CLARIFY, "clarification", message=message)


def _conversation() -> IntentRoute:
    return IntentRoute(RouteOutcome.CONVERSATION, "conversation")


def route_prompt(prompt: str) -> IntentRoute:
    """Return a deterministic route without calling a model or TeamViewer."""
    text = " ".join(prompt.strip().split())
    lowered = text.casefold()
    if not text:
        return _conversation()

    if _NEGATED_OPERATION.search(text) or _INFORMATIONAL_OPERATION.search(text):
        return _conversation()

    if _has_multiple_operations(text):
        return _clarify("Request one TeamViewer operation at a time.")

    explicit = _EXPLICIT_TOOL.findall(text)
    if explicit:
        names = {name.casefold() for name in explicit}
        if len(names) != 1:
            return _clarify("Request one TeamViewer operation at a time.")
        tool_name = names.pop()
        if tool_name in UNSAFE_DISABLED_TOOLS:
            return _clarify(
                f"{tool_name} is disabled because its upstream MCP argument schema "
                "is not safe enough."
            )
        if tool_name not in READ_ONLY_TOOLS | APPROVAL_REQUIRED_TOOLS:
            return _clarify(f"{tool_name} is not available under the current safety policy.")
        if tool_name == "tv_create_session":
            create_error = _create_session_prompt_error(text)
            if create_error:
                return _clarify(create_error)
        return _tool_route(f"explicit:{tool_name}", tool_name)

    write_matches = _write_matches(text, lowered)
    if _has_unsupported_write(text, lowered):
        return _clarify(
            "That state-changing TeamViewer operation is not supported by this application's "
            "safety policy."
        )
    if len(write_matches) > 1:
        return _clarify("Request one state-changing TeamViewer operation at a time.")
    if write_matches:
        intent, tool_name = write_matches[0]
        if tool_name == "tv_create_session":
            create_error = _create_session_prompt_error(text)
            if create_error:
                return _clarify(create_error)
        if _has_multiple_write_targets(text) or any(
            re.search(pattern, lowered)
            for pattern in (
                r"\bsessions\b",
                r"\bmanaged[ -]devices\b",
                r"\bconnection[ -]reports\b",
                r"\bteamviewer\s+ids\b",
            )
        ):
            return _clarify("Request exactly one target for a state-changing operation.")
        if tool_name in UNSAFE_DISABLED_TOOLS:
            return _clarify(
                "Policy assignment is temporarily disabled because the official TeamViewer MCP "
                "schema does not define a safe typed assignment payload."
            )
        return _tool_route(intent, tool_name)

    # Never reinterpret an unsupported state change as a related read operation.
    # This is deliberately before every read route.
    weak_read_phrase = (
        _READ_REQUEST.search(text) is not None
        and _STRONG_MUTATING_VERB.search(text) is None
    )
    if _MUTATING_VERB.search(text) and not weak_read_phrase:
        return _clarify(
            "That state-changing TeamViewer operation is not supported by this application's "
            "safety policy."
        )

    # Ordered from the most specific vocabulary to the most general.
    if "account" in lowered and any(
        word in lowered for word in ("summary", "data", "detail", "email")
    ):
        return _tool_route("account_summary", "tv_get_account")
    if "license" in lowered:
        return _tool_route("company_license", "tv_get_company_license")
    if "company" in lowered and any(
        word in lowered for word in ("summary", "data", "detail", "information")
    ):
        return _tool_route("company_details", "tv_get_company")
    if "event log" in lowered or "audit log" in lowered:
        return _tool_route("event_logs", "tv_get_event_logs")
    if "connection" in lowered and "ai summary" in lowered:
        return _tool_route("connection_ai_summary", "tv_get_connection_ai_summary")
    if "device report" in lowered:
        return _tool_route("device_reports", "tv_list_device_reports")
    if "connection report" in lowered:
        if any(word in lowered for word in ("list", "reports", "all")):
            return _tool_route("connection_reports", "tv_list_connection_reports")
        return _tool_route("connection_report", "tv_get_connection_report")
    if "monitoring alarm" in lowered or "monitoring alert" in lowered:
        return _tool_route("monitoring_alarms", "tv_list_monitoring_alarms")
    if "monitored device" in lowered or "monitored devices" in lowered:
        return _tool_route("monitoring_devices", "tv_list_monitoring_devices")
    if "hardware" in lowered and "device" in lowered:
        return _tool_route("device_hardware", "tv_get_device_hardware_info")
    if "software" in lowered and "device" in lowered:
        return _tool_route("device_software", "tv_get_device_software_info")
    if "system" in lowered and "device" in lowered:
        return _tool_route("device_system", "tv_get_device_system_info")
    if "monitoring" in lowered and "device" in lowered:
        return _tool_route("monitoring_devices", "tv_list_monitoring_devices")
    if "session" in lowered:
        if any(word in lowered for word in ("list", "sessions", "all")):
            return _tool_route("sessions", "tv_list_sessions")
        return _tool_route("session", "tv_get_session")
    if "company-managed" in lowered or "company managed" in lowered:
        return _tool_route("company_managed_devices", "tv_list_company_managed_devices")
    if "directly managed" in lowered:
        return _tool_route("managed_devices", "tv_list_managed_devices")
    if "managed device" in lowered and "group" in lowered:
        if any(
            phrase in lowered
            for phrase in (
                "belongs to",
                "part of",
                "device groups",
                "groups contain",
                "groups include",
                "which groups",
            )
        ):
            return _tool_route("managed_device_groups", "tv_get_managed_device_groups")
    if "device group" in lowered and any(
        word in lowered for word in ("list", "groups", "all")
    ):
        return _tool_route("legacy_groups", "tv_list_device_groups")
    if "device" in lowered and (
        re.search(r"(?:\bin\b|\bfrom\b|\bof\b|\bbelong(?:s|ing)?\s+to\b).{0,80}group", lowered)
        or re.search(r"group.{0,80}\bdevices?\b", lowered)
    ):
        return _tool_route("group_devices", "tv_list_devices_in_group")
    if "managed group" in lowered:
        if any(word in lowered for word in ("list", "groups", "all")):
            return _tool_route("managed_groups", "tv_list_managed_groups")
        return _tool_route("managed_group", "tv_list_managed_groups")
    if "group" in lowered:
        if any(word in lowered for word in ("list", "groups", "all")):
            return _tool_route("legacy_groups", "tv_list_device_groups")
        return _tool_route("legacy_group", "tv_get_device_group")
    if "managed device" in lowered:
        if any(word in lowered for word in ("list", "devices", "all", "online")):
            return _tool_route("managed_devices", "tv_list_managed_devices")
        return _tool_route("managed_device", "tv_get_managed_device")
    if "device" in lowered:
        if any(word in lowered for word in ("list", "devices", "all", "online", "offline")):
            return _tool_route("legacy_devices", "tv_list_devices")
        return _tool_route("legacy_device", "tv_get_device")

    if "teamviewer" in lowered and _OPERATIONAL_VERB.search(text):
        return _clarify(
            "I could not map that request to one safe TeamViewer operation. Specify the object, "
            "action, and identifier."
        )
    return _conversation()
