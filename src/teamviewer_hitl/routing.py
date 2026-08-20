"""Deterministic, fail-closed routing for TeamViewer operator requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .policy import APPROVAL_REQUIRED_TOOLS, READ_ONLY_TOOLS, UNSAFE_DISABLED_TOOLS


class RouteOutcome(str, Enum):
    TOOL = "tool"
    HOST = "host"
    CONVERSATION = "conversation"
    CLARIFY = "clarify"


@dataclass(frozen=True, slots=True)
class IntentRoute:
    outcome: RouteOutcome
    intent: str
    tool_name: str | None = None
    mutating: bool = False
    message: str | None = None
    arguments: tuple[tuple[str, Any], ...] = ()


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
_SAFE_IDENTIFIER_TEXT = r"[A-Za-z0-9_-]+"
_UUID_TEXT = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_SESSION_CODE_SELECTOR = re.compile(
    rf"\bsession\s+code\s+(?P<session_code>{_SAFE_IDENTIFIER_TEXT})\b",
    re.IGNORECASE,
)
_TEAMVIEWER_ID_SELECTOR = re.compile(
    r"\bteamviewer\s+id\s+(?P<teamviewer_id>[0-9]+)\b", re.IGNORECASE
)
_SESSION_UPDATE_PATTERNS = (
    re.compile(
        rf"\bsession\s+code\s+(?P<session_code>{_SAFE_IDENTIFIER_TEXT})\b"
        r".{0,100}?\b(?:with\s+)?description(?:\s+to)?\s+"
        r"(?P<description>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bdescription\s+of\s+(?:teamviewer\s+)?session\s+code\s+"
        rf"(?P<session_code>{_SAFE_IDENTIFIER_TEXT})\s+to\s+"
        r"(?P<description>.+)$",
        re.IGNORECASE,
    ),
)
_MANAGED_DEVICE_UPDATE_PATTERNS = (
    re.compile(
        rf"\bmanaged[ -]device\s+id\s+(?P<device_id>{_UUID_TEXT})\b"
        r".{0,80}?\b(?:with\s+)?description(?:\s+to)?\s+"
        r"(?P<description>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bdescription\s+of\s+managed[ -]device\s+id\s+"
        rf"(?P<device_id>{_UUID_TEXT})\s+to\s+(?P<description>.+)$",
        re.IGNORECASE,
    ),
)
_CONNECTION_REPORT_UPDATE = re.compile(
    rf"\bconnection[ -]report\s+id\s+(?P<connection_id>{_UUID_TEXT})\b"
    r".{0,80}?\b(?:with\s+)?notes?(?:\s+to)?\s+(?P<notes>.+)$",
    re.IGNORECASE,
)
_UNSUPPORTED_SESSION_METADATA = re.compile(
    r"\b(?:notes?|tags?|supporter(?:\s+name)?|end[ -]customer)\b",
    re.IGNORECASE,
)
_POLICY_SELECTOR = re.compile(
    r"\b(?:monitoring|patch(?:\s+management)?)\s+policy\s+id\b",
    re.IGNORECASE,
)
_NAMED_GROUP_PATTERNS = (
    re.compile(
        r"\bdevices?(?:\s+are)?\s+(?:in|from|of|belong(?:s|ing)?\s+to)\s+"
        r"(?:(?:managed|legacy)\s+)?(?:group(?:\s+name)?\s+)?"
        r"(?P<group_name>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\blist\s+(?P<group_name>.+?)\s+devices?\b", re.IGNORECASE
    ),
)
_WRITE_GUIDANCE: dict[str, str] = {
    "tv_update_session": (
        "Session updates support exactly one session code and one description, for example: "
        "'Update TeamViewer session code s123 with description Escalated case'."
    ),
    "tv_delete_session": (
        "Closing a session requires exactly one immediate 'session code <CODE>' selector."
    ),
    "tv_update_managed_device_description": (
        "Managed-device description updates require one canonical device UUID and one description."
    ),
    "tv_activate_monitoring": (
        "Monitoring activation requires exactly one numeric 'TeamViewer ID <ID>' and does not "
        "accept policy selectors in this safety profile."
    ),
    "tv_update_connection_report": (
        "Connection-report updates require one report UUID and one notes value."
    ),
}


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


def _clean_mutable_value(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1].strip()
    return cleaned[:-1].rstrip() if cleaned.endswith(".") else cleaned


def _single_pattern_match(
    patterns: tuple[re.Pattern[str], ...], text: str
) -> re.Match[str] | None:
    matches = [match for pattern in patterns for match in pattern.finditer(text)]
    return matches[0] if len(matches) == 1 else None


def _write_arguments(tool_name: str, text: str) -> dict[str, Any] | None:
    """Extract the exact state-changing call authorized by the operator's words."""
    if tool_name == "tv_create_session":
        if _create_session_prompt_error(text) or _UNSUPPORTED_SESSION_METADATA.search(text):
            return None
        return {
            "description": create_session_descriptions(text)[0],
            "groupid": create_session_group_ids(text)[0],
        }

    if tool_name == "tv_update_session":
        if _UNSUPPORTED_SESSION_METADATA.search(text):
            return None
        match = _single_pattern_match(_SESSION_UPDATE_PATTERNS, text)
        if match is None or len(_SESSION_CODE_SELECTOR.findall(text)) != 1:
            return None
        description = _clean_mutable_value(match.group("description"))
        if not description:
            return None
        return {
            "session_code": match.group("session_code"),
            "description": description,
        }

    if tool_name == "tv_delete_session":
        matches = list(_SESSION_CODE_SELECTOR.finditer(text))
        if len(matches) != 1:
            return None
        return {"session_code": matches[0].group("session_code")}

    if tool_name == "tv_update_managed_device_description":
        match = _single_pattern_match(_MANAGED_DEVICE_UPDATE_PATTERNS, text)
        if match is None:
            return None
        description = _clean_mutable_value(match.group("description"))
        if not description:
            return None
        return {
            "device_id": match.group("device_id").casefold(),
            "description": description,
        }

    if tool_name == "tv_activate_monitoring":
        matches = list(_TEAMVIEWER_ID_SELECTOR.finditer(text))
        if len(matches) != 1 or _POLICY_SELECTOR.search(text):
            return None
        value = int(matches[0].group("teamviewer_id"))
        if not 0 < value <= 9_007_199_254_740_991:
            return None
        return {"teamviewer_id": value}

    if tool_name == "tv_update_connection_report":
        matches = list(_CONNECTION_REPORT_UPDATE.finditer(text))
        if len(matches) != 1:
            return None
        notes = _clean_mutable_value(matches[0].group("notes"))
        if not notes:
            return None
        return {
            "connection_id": matches[0].group("connection_id").casefold(),
            "notes": notes,
        }

    return None


def _write_prompt_error(tool_name: str, text: str) -> str | None:
    if tool_name == "tv_create_session":
        create_error = _create_session_prompt_error(text)
        if create_error:
            return create_error
        if _UNSUPPORTED_SESSION_METADATA.search(text):
            return (
                "Session creation supports only description and an existing legacy group ID; "
                "optional session metadata is disabled because the official API does not "
                "define the MCP server's extra fields."
            )
        return None
    if _write_arguments(tool_name, text) is None:
        return _WRITE_GUIDANCE[tool_name]
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


def _tool_route(
    intent: str, tool_name: str, arguments: dict[str, Any] | None = None
) -> IntentRoute:
    return IntentRoute(
        outcome=RouteOutcome.TOOL,
        intent=intent,
        tool_name=tool_name,
        mutating=tool_name in APPROVAL_REQUIRED_TOOLS,
        arguments=tuple((arguments or {}).items()),
    )


def _host_route(intent: str, arguments: dict[str, Any]) -> IntentRoute:
    """Route deterministic MCP orchestration that exposes no model tool."""
    return IntentRoute(
        outcome=RouteOutcome.HOST,
        intent=intent,
        arguments=tuple(arguments.items()),
    )


def _availability_arguments(text: str) -> tuple[dict[str, Any] | None, str | None]:
    states = [
        value
        for value in ("Online", "Offline")
        if re.search(rf"\b{value}\b", text, re.IGNORECASE)
    ]
    if len(states) > 1:
        return None, "Request either online devices or offline devices, not both."
    return ({"online_state": states[0]} if states else None), None


def _explicit_read_arguments(
    tool_name: str, text: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Bind supported optional filters on an explicitly named read tool."""
    lowered = text.casefold()
    if tool_name == "tv_list_devices":
        arguments, error = _availability_arguments(text)
        if error:
            return None, error
        if re.search(r"\b(?:shared|alias|remote\s+control)\b", lowered):
            return None, (
                "Legacy device lists expose only group ID and online/offline filters."
            )
        group_labels = re.findall(r"\bgroup\s+(?:id|name)\b", text, re.IGNORECASE)
        group_ids = re.findall(r"\bgroup\s+id\s+(g[0-9]+)\b", text, re.IGNORECASE)
        if len(group_labels) > 1 or (group_labels and len(group_ids) != 1):
            return None, "Use at most one exact legacy 'group ID g<number>' filter."
        if group_ids:
            arguments = dict(arguments or {})
            arguments["groupid"] = group_ids[0]
        return arguments, None

    if tool_name in {
        "tv_list_managed_devices",
        "tv_list_company_managed_devices",
    }:
        if re.search(
            r"\b(?:group|user|policy|name|description)\b|\bdevice\s+id\b",
            lowered,
        ):
            return None, "Managed-device lists expose only an online/offline filter."
        return _availability_arguments(text)

    if tool_name == "tv_list_sessions":
        if re.search(
            r"\b(?:tag|group\s+id|assigned\s+user|full\s+list|session\s+code|"
            r"from|to|user)\b",
            lowered,
        ):
            return None, (
                "Session listing exposes only one optional open/closed state filter."
            )
        states = [
            value
            for value in ("open", "closed")
            if re.search(rf"\b{value}\b", lowered)
        ]
        if len(states) > 1:
            return None, "Request either open sessions or closed sessions, not both."
        return ({"state": states[0]} if states else None), None

    if tool_name == "tv_list_device_groups":
        if re.search(r"\b(?:shared|name|owner|permission|group\s+id)\b", lowered):
            return None, "Filtered legacy group listing is not exposed."
        return None, None

    if tool_name == "tv_list_managed_groups":
        if re.search(r"\bgroup\s+(?:id|name)\b", lowered):
            return None, "Filtered managed-group listing is not exposed."
        return None, None

    if tool_name == "tv_list_monitoring_devices":
        if re.search(r"\b(?:teamviewer|device|group|policy)\s+id\b", lowered):
            return None, "Filtered monitoring-device listing is not exposed."
        return None, None

    filtered_patterns = {
        "tv_list_connection_reports": (
            r"\b(?:user|group|device|session)\s+(?:id|code)\b|"
            r"\b(?:from|to|limit|offset|for|where|with|email)\b"
        ),
        "tv_list_device_reports": (
            r"\b(?:user|origin|target|device|report)\s+id\b|"
            r"\b(?:from|to|limit|offset|for|where|with)\b"
        ),
        "tv_list_monitoring_alarms": (
            r"\b(?:open|closed|status|alarm\s+id|device\s+id|group\s+id|"
            r"from|to|for|where|with)\b"
        ),
    }
    pattern = filtered_patterns.get(tool_name)
    if pattern and re.search(pattern, lowered):
        return None, (
            f"Filtered {tool_name} requests are disabled in this safety profile; "
            "request the complete list."
        )
    return None, None


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
        if tool_name in APPROVAL_REQUIRED_TOOLS:
            write_error = _write_prompt_error(tool_name, text)
            if write_error:
                return _clarify(write_error)
            return _tool_route(
                f"explicit:{tool_name}", tool_name, _write_arguments(tool_name, text)
            )
        arguments, read_error = _explicit_read_arguments(tool_name, text)
        if read_error:
            return _clarify(read_error)
        return _tool_route(f"explicit:{tool_name}", tool_name, arguments)

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
        if tool_name in UNSAFE_DISABLED_TOOLS:
            return _clarify(
                "Policy assignment is temporarily disabled because the official TeamViewer MCP "
                "schema does not define a safe typed assignment payload."
            )
        write_error = _write_prompt_error(tool_name, text)
        if write_error:
            return _clarify(write_error)
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
        return _tool_route(
            intent, tool_name, _write_arguments(tool_name, text)
        )

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
        arguments, error = _explicit_read_arguments("tv_list_device_reports", text)
        return _clarify(error) if error else _tool_route(
            "device_reports", "tv_list_device_reports", arguments
        )
    if "connection report" in lowered:
        if any(word in lowered for word in ("list", "reports", "all")):
            arguments, error = _explicit_read_arguments(
                "tv_list_connection_reports", text
            )
            return _clarify(error) if error else _tool_route(
                "connection_reports", "tv_list_connection_reports", arguments
            )
        return _tool_route("connection_report", "tv_get_connection_report")
    if "monitoring alarm" in lowered or "monitoring alert" in lowered:
        arguments, error = _explicit_read_arguments("tv_list_monitoring_alarms", text)
        return _clarify(error) if error else _tool_route(
            "monitoring_alarms", "tv_list_monitoring_alarms", arguments
        )
    if "hardware" in lowered and "device" in lowered:
        return _tool_route("device_hardware", "tv_get_device_hardware_info")
    if "software" in lowered and "device" in lowered:
        return _tool_route("device_software", "tv_get_device_software_info")
    if "system" in lowered and "device" in lowered:
        return _tool_route("device_system", "tv_get_device_system_info")
    if "monitored device" in lowered or "monitored devices" in lowered:
        if re.search(r"\b(?:teamviewer|device|group|policy)\s+id\b", lowered):
            return _clarify(
                "Filtered monitoring-device listing is not exposed; request all monitored "
                "devices, or request hardware, system, or software by TeamViewer ID."
            )
        return _tool_route("monitoring_devices", "tv_list_monitoring_devices")
    if "monitoring" in lowered and "device" in lowered:
        if re.search(r"\b(?:teamviewer|device|group|policy)\s+id\b", lowered):
            return _clarify(
                "Filtered monitoring-device listing is not exposed; request all monitored "
                "devices, or request hardware, system, or software by TeamViewer ID."
            )
        return _tool_route("monitoring_devices", "tv_list_monitoring_devices")
    if "session" in lowered:
        session_codes = list(_SESSION_CODE_SELECTOR.finditer(text))
        if len(session_codes) == 1 and not re.search(r"\bsessions\b", lowered):
            return _tool_route("session", "tv_get_session")
        if len(session_codes) > 1:
            return _clarify("Request exactly one TeamViewer session code.")
        arguments, error = _explicit_read_arguments("tv_list_sessions", text)
        if error:
            return _clarify(error)
        if arguments is not None or any(
            word in lowered for word in ("list", "sessions", "all")
        ):
            return _tool_route("sessions", "tv_list_sessions", arguments)
        return _tool_route("session", "tv_get_session")
    if "company-managed" in lowered or "company managed" in lowered:
        arguments, error = _explicit_read_arguments(
            "tv_list_company_managed_devices", text
        )
        if error:
            return _clarify(error)
        return _tool_route(
            "company_managed_devices", "tv_list_company_managed_devices", arguments
        )
    if "directly managed" in lowered:
        arguments, error = _explicit_read_arguments("tv_list_managed_devices", text)
        if error:
            return _clarify(error)
        return _tool_route("managed_devices", "tv_list_managed_devices", arguments)
    if re.search(r"\bmanaged[ -]device\s+groups\b", lowered) and not re.search(
        r"\bmanaged[ -]device\s+id\b", lowered
    ):
        return _tool_route("managed_groups", "tv_list_managed_groups")
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
        if re.search(r"\b(?:shared|name|owner|permission)\b", lowered):
            return _clarify("Filtered legacy group listing is not exposed.")
        return _tool_route("legacy_groups", "tv_list_device_groups")
    if "device" in lowered and (
        re.search(r"(?:\bin\b|\bfrom\b|\bof\b|\bbelong(?:s|ing)?\s+to\b).{0,80}group", lowered)
        or re.search(r"group.{0,80}\bdevices?\b", lowered)
    ):
        group_id_match = re.search(
            r"\bgroup\s+id\s+(?P<groupid>g[0-9]+)\b", text, re.IGNORECASE
        )
        if group_id_match:
            arguments, error = _explicit_read_arguments("tv_list_devices", text)
            if error:
                return _clarify(error)
            return _tool_route(
                "legacy_group_devices",
                "tv_list_devices",
                arguments,
            )
        explicit = re.search(r"\bgroup\s+name\s+(?P<name>.+)$", text, re.IGNORECASE)
        match = explicit or _single_pattern_match(_NAMED_GROUP_PATTERNS, text)
        if match is None:
            return _clarify(
                "Supply exactly one explicit group name for the device-list request."
            )
        group_name = _clean_mutable_value(
            match.group("name") if explicit else match.group("group_name")
        )
        if not group_name:
            return _clarify("Supply a non-empty group name.")
        return _host_route("group_devices", {"group_name": group_name})
    if "managed group" in lowered:
        if any(word in lowered for word in ("list", "groups", "all")):
            return _tool_route("managed_groups", "tv_list_managed_groups")
        return _clarify(
            "Request all managed groups, or use the exact group name in a device-list request."
        )
    if "group" in lowered:
        if any(word in lowered for word in ("list", "groups", "all")):
            return _tool_route("legacy_groups", "tv_list_device_groups")
        return _tool_route("legacy_group", "tv_get_device_group")
    if "managed device" in lowered:
        if any(word in lowered for word in ("list", "devices", "all", "online")):
            arguments, error = _explicit_read_arguments(
                "tv_list_managed_devices", text
            )
            if error:
                return _clarify(error)
            return _tool_route("managed_devices", "tv_list_managed_devices", arguments)
        return _tool_route("managed_device", "tv_get_managed_device")
    if "device" in lowered:
        if any(word in lowered for word in ("list", "devices", "all", "online", "offline")):
            arguments, error = _explicit_read_arguments("tv_list_devices", text)
            if error:
                return _clarify(error)
            if "legacy" in lowered or "computers & contacts" in lowered:
                return _tool_route("legacy_devices", "tv_list_devices", arguments)
            return _host_route("all_devices", arguments or {})
        return _tool_route("legacy_device", "tv_get_device")

    if "teamviewer" in lowered and _OPERATIONAL_VERB.search(text):
        return _clarify(
            "I could not map that request to one safe TeamViewer operation. Specify the object, "
            "action, and identifier."
        )
    return _conversation()
