"""Typed read adapters that keep every TeamViewer request inside MCP."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from agent_framework import tool
from pydantic import Field

from .mcp_compositions import TeamViewerMCPReadError

_MAX_PAGES = 100
_UUID_IN_TEXT = re.compile(
    r"(?<![0-9a-fA-F])"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"(?![0-9a-fA-F])"
)


def _decode_mcp_json(result: Any, tool_name: str) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    if isinstance(result, str):
        text = result
    elif isinstance(result, list):
        text = "".join(
            item.text
            for item in result
            if isinstance(getattr(item, "text", None), str)
        )
    else:
        raise TeamViewerMCPReadError(f"{tool_name} returned an unexpected result type")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TeamViewerMCPReadError(f"{tool_name} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise TeamViewerMCPReadError(f"{tool_name} returned an unexpected JSON shape")
    return payload


def _list_value(payload: Mapping[str, Any], tool_name: str, *keys: str) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    raise TeamViewerMCPReadError(
        f"{tool_name} did not return an expected collection ({', '.join(keys)})"
    )


def _next_string(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise TeamViewerMCPReadError(f"{key} was not a string")
        return value
    return None


def _report_cursor(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        pass

    parsed = urlparse(value)
    for key in ("offset_id", "offsetId"):
        candidates = parse_qs(parsed.query).get(key, [])
        if candidates:
            try:
                return str(UUID(candidates[0]))
            except ValueError as exc:
                raise TeamViewerMCPReadError(
                    "TeamViewer returned an invalid report pagination cursor"
                ) from exc

    match = _UUID_IN_TEXT.search(value)
    if match:
        return str(UUID(match.group(0)))
    raise TeamViewerMCPReadError(
        "TeamViewer returned an unrecognized report pagination cursor"
    )


async def _all_token_resources(teamviewer: Any, tool_name: str) -> dict[str, Any]:
    resources: list[Any] = []
    token: str | None = None
    seen: set[str] = set()

    for _ in range(_MAX_PAGES):
        arguments = {"pagination_token": token} if token else {}
        payload = _decode_mcp_json(
            await teamviewer.call_tool(tool_name, **arguments), tool_name
        )
        resources.extend(_list_value(payload, tool_name, "resources"))
        token = _next_string(payload, "nextPaginationToken")
        if token is None:
            return {"resources": resources, "nextPaginationToken": None}
        if token in seen:
            raise TeamViewerMCPReadError(
                f"{tool_name} repeated a pagination token"
            )
        seen.add(token)

    raise TeamViewerMCPReadError(f"{tool_name} exceeded the pagination safety limit")


async def _all_report_records(teamviewer: Any, tool_name: str) -> dict[str, Any]:
    records: list[Any] = []
    cursor: str | None = None
    seen: set[str] = set()

    for _ in range(_MAX_PAGES):
        arguments = {"offset_id": cursor} if cursor else {}
        payload = _decode_mcp_json(
            await teamviewer.call_tool(tool_name, **arguments), tool_name
        )
        records.extend(_list_value(payload, tool_name, "records"))
        next_offset = _next_string(payload, "next_offset")
        remaining = payload.get("records_remaining")
        if next_offset is None:
            if isinstance(remaining, int) and remaining > 0:
                raise TeamViewerMCPReadError(
                    f"{tool_name} reported more records without a cursor"
                )
            return {
                "records": records,
                "records_remaining": 0,
                "next_offset": None,
            }
        cursor = _report_cursor(next_offset)
        if cursor in seen:
            raise TeamViewerMCPReadError(f"{tool_name} repeated a report cursor")
        seen.add(cursor)

    raise TeamViewerMCPReadError(f"{tool_name} exceeded the pagination safety limit")


def create_mcp_read_tools(teamviewer: Any) -> list[Any]:
    """Create strict read adapters over the official TeamViewer MCP tools."""

    @tool(approval_mode="never_require")
    async def tv_list_managed_devices(
        online_state: Annotated[
            Literal["Online", "Offline"] | None,
            Field(description="Optional exact availability filter applied by the host"),
        ] = None,
    ) -> dict[str, Any]:
        """List every directly managed device through bounded MCP pagination."""
        payload = await _all_token_resources(teamviewer, "tv_list_managed_devices")
        if online_state is not None:
            expected = online_state == "Online"
            payload["resources"] = [
                item
                for item in payload["resources"]
                if isinstance(item, Mapping) and item.get("isOnline") is expected
            ]
        return payload

    @tool(approval_mode="never_require")
    async def tv_list_company_managed_devices(
        online_state: Annotated[
            Literal["Online", "Offline"] | None,
            Field(description="Optional exact availability filter applied by the host"),
        ] = None,
    ) -> dict[str, Any]:
        """List every company-managed device through bounded MCP pagination."""
        payload = await _all_token_resources(
            teamviewer, "tv_list_company_managed_devices"
        )
        if online_state is not None:
            expected = online_state == "Online"
            payload["resources"] = [
                item
                for item in payload["resources"]
                if isinstance(item, Mapping) and item.get("isOnline") is expected
            ]
        return payload

    @tool(approval_mode="never_require")
    async def tv_list_managed_groups() -> dict[str, Any]:
        """List managed groups only when the upstream MCP response is complete."""
        payload = _decode_mcp_json(
            await teamviewer.call_tool("tv_list_managed_groups"),
            "tv_list_managed_groups",
        )
        _list_value(payload, "tv_list_managed_groups", "resources")
        if _next_string(payload, "nextPaginationToken") is not None:
            raise TeamViewerMCPReadError(
                "The official MCP managed-group tool cannot forward paginationToken"
            )
        return payload

    @tool(approval_mode="never_require")
    async def tv_list_monitoring_alarms() -> dict[str, Any]:
        """List every monitoring alarm through bounded MCP pagination."""
        alarms: list[Any] = []
        token: str | None = None
        seen: set[str] = set()
        for _ in range(_MAX_PAGES):
            arguments = {"continuation_token": token} if token else {}
            payload = _decode_mcp_json(
                await teamviewer.call_tool(
                    "tv_list_monitoring_alarms", **arguments
                ),
                "tv_list_monitoring_alarms",
            )
            alarms.extend(
                _list_value(payload, "tv_list_monitoring_alarms", "Alarms", "alarms")
            )
            token = _next_string(
                payload, "ContinuationToken", "continuationToken"
            )
            if token is None:
                return {"Alarms": alarms, "ContinuationToken": None}
            if token in seen:
                raise TeamViewerMCPReadError(
                    "tv_list_monitoring_alarms repeated a continuation token"
                )
            seen.add(token)
        raise TeamViewerMCPReadError(
            "tv_list_monitoring_alarms exceeded the pagination safety limit"
        )

    @tool(approval_mode="never_require")
    async def tv_get_device_hardware_info(
        teamviewer_id: Annotated[
            int,
            Field(
                gt=0,
                le=9_007_199_254_740_991,
                description="Numeric TeamViewer ID of the monitored device",
            ),
        ],
    ) -> Any:
        """Get monitored-device hardware using the API's numeric device identifier."""
        return await teamviewer.call_tool(
            "tv_get_device_hardware_info", device_id=str(teamviewer_id)
        )

    @tool(approval_mode="never_require")
    async def tv_get_device_system_info(
        teamviewer_id: Annotated[
            int,
            Field(
                gt=0,
                le=9_007_199_254_740_991,
                description="Numeric TeamViewer ID of the monitored device",
            ),
        ],
    ) -> Any:
        """Get monitored-device system data using its numeric TeamViewer ID."""
        return await teamviewer.call_tool(
            "tv_get_device_system_info", device_id=str(teamviewer_id)
        )

    @tool(approval_mode="never_require")
    async def tv_get_device_software_info(
        teamviewer_id: Annotated[
            int,
            Field(
                gt=0,
                le=9_007_199_254_740_991,
                description="Numeric TeamViewer ID of the monitored device",
            ),
        ],
    ) -> Any:
        """Get monitored-device software using its numeric TeamViewer ID."""
        return await teamviewer.call_tool(
            "tv_get_device_software_info", device_id=str(teamviewer_id)
        )

    @tool(approval_mode="never_require")
    async def tv_list_connection_reports() -> dict[str, Any]:
        """List every connection report through the API's UUID cursor."""
        return await _all_report_records(teamviewer, "tv_list_connection_reports")

    @tool(approval_mode="never_require")
    async def tv_list_device_reports() -> dict[str, Any]:
        """List every device report through the API's UUID cursor."""
        return await _all_report_records(teamviewer, "tv_list_device_reports")

    @tool(approval_mode="never_require")
    async def tv_get_event_logs(
        start_date: Annotated[str, Field(min_length=1, max_length=64)],
        end_date: Annotated[str, Field(min_length=1, max_length=64)],
    ) -> dict[str, Any]:
        """Read event logs and fail closed if the upstream tool cannot fetch all pages."""
        payload = _decode_mcp_json(
            await teamviewer.call_tool(
                "tv_get_event_logs", start_date=start_date, end_date=end_date
            ),
            "tv_get_event_logs",
        )
        if _next_string(
            payload, "ContinuationToken", "continuationToken", "PaginationToken"
        ) is not None:
            raise TeamViewerMCPReadError(
                "The official MCP event-log tool sends the next-page token under "
                "the wrong API field"
            )
        return payload

    @tool(approval_mode="never_require")
    async def tv_list_sessions(
        state: Annotated[
            Literal["open", "closed"] | None,
            Field(description="Optional exact session state filter"),
        ] = None,
    ) -> dict[str, Any]:
        """List sessions and fail closed if the upstream tool cannot fetch all pages."""
        arguments = {"state": state} if state is not None else {}
        payload = _decode_mcp_json(
            await teamviewer.call_tool("tv_list_sessions", **arguments),
            "tv_list_sessions",
        )
        remaining = payload.get("sessions_remaining")
        if _next_string(payload, "next_offset") is not None or (
            isinstance(remaining, int) and remaining > 0
        ):
            raise TeamViewerMCPReadError(
                "The official MCP session-list tool does not expose the API offset cursor"
            )
        return payload

    return [
        tv_list_managed_devices,
        tv_list_company_managed_devices,
        tv_list_managed_groups,
        tv_list_monitoring_alarms,
        tv_get_device_hardware_info,
        tv_get_device_system_info,
        tv_get_device_software_info,
        tv_list_connection_reports,
        tv_list_device_reports,
        tv_get_event_logs,
        tv_list_sessions,
    ]
