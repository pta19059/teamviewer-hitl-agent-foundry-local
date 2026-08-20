"""Read-only compositions built exclusively from official TeamViewer MCP tools."""

from __future__ import annotations

import json
from typing import Any


class TeamViewerMCPReadError(RuntimeError):
    """Raised when an MCP-only TeamViewer composition cannot be completed safely."""


def _decode_mcp_json(result: Any, tool_name: str) -> dict[str, Any]:
    if isinstance(result, str):
        text = result
    elif isinstance(result, list):
        text = "".join(
            item.text for item in result if isinstance(getattr(item, "text", None), str)
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


def _resources(payload: dict[str, Any], tool_name: str) -> list[dict[str, Any]]:
    resources = payload.get("resources")
    if not isinstance(resources, list):
        raise TeamViewerMCPReadError(f"{tool_name} did not return a resource list")
    return [resource for resource in resources if isinstance(resource, dict)]


async def _list_managed_groups(teamviewer: Any) -> list[dict[str, Any]]:
    page_size = 100
    groups: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for offset in range(0, 10_000, page_size):
        payload = _decode_mcp_json(
            await teamviewer.call_tool(
                "tv_list_managed_groups", limit=page_size, offset=offset
            ),
            "tv_list_managed_groups",
        )
        page = _resources(payload, "tv_list_managed_groups")
        page_ids = {str(group.get("id")) for group in page}
        if page and page_ids <= seen_ids:
            raise TeamViewerMCPReadError(
                "tv_list_managed_groups repeated a page instead of advancing pagination"
            )
        groups.extend(page)
        seen_ids.update(page_ids)
        if len(page) < page_size:
            return groups

    raise TeamViewerMCPReadError("Managed-group pagination exceeded the safety limit")


async def _list_company_managed_devices(teamviewer: Any) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    pagination_token: str | None = None
    seen_tokens: set[str] = set()

    for _ in range(100):
        arguments = {"pagination_token": pagination_token} if pagination_token else {}
        payload = _decode_mcp_json(
            await teamviewer.call_tool("tv_list_company_managed_devices", **arguments),
            "tv_list_company_managed_devices",
        )
        devices.extend(_resources(payload, "tv_list_company_managed_devices"))

        next_token = payload.get("nextPaginationToken")
        if not next_token:
            return devices
        if not isinstance(next_token, str) or next_token in seen_tokens:
            raise TeamViewerMCPReadError(
                "tv_list_company_managed_devices returned an invalid pagination token"
            )
        seen_tokens.add(next_token)
        pagination_token = next_token

    raise TeamViewerMCPReadError("Managed-device pagination exceeded the safety limit")


async def list_devices_in_managed_group(
    teamviewer: Any, group_name: str
) -> dict[str, Any]:
    """Return exact managed-group membership using only TeamViewer MCP tool calls."""
    requested_name = group_name.strip()
    if not requested_name:
        raise TeamViewerMCPReadError("Managed group name cannot be empty")

    groups = await _list_managed_groups(teamviewer)
    matches = [
        group
        for group in groups
        if str(group.get("name", "")).casefold() == requested_name.casefold()
    ]
    if not matches:
        return {
            "status": "not_found",
            "requestedGroupName": requested_name,
            "message": "No managed group matched the requested name exactly.",
        }
    if len(matches) > 1:
        return {
            "status": "ambiguous",
            "requestedGroupName": requested_name,
            "matches": [
                {"id": group.get("id"), "name": group.get("name")} for group in matches
            ],
            "message": "More than one managed group has the requested name.",
        }

    group = matches[0]
    group_id = str(group.get("id", ""))
    if not group_id:
        raise TeamViewerMCPReadError("TeamViewer MCP returned a managed group without an ID")

    selected_devices: list[dict[str, Any]] = []
    for device in await _list_company_managed_devices(teamviewer):
        device_id = str(device.get("id", ""))
        if not device_id:
            continue
        membership = _decode_mcp_json(
            await teamviewer.call_tool(
                "tv_get_managed_device_groups", device_id=device_id
            ),
            "tv_get_managed_device_groups",
        )
        device_groups = _resources(membership, "tv_get_managed_device_groups")
        if not any(str(item.get("id", "")) == group_id for item in device_groups):
            continue

        selected_devices.append(
            {
                "id": device.get("id"),
                "teamviewerId": device.get("teamviewerId"),
                "name": device.get("name"),
                "availability": (
                    "Online"
                    if device.get("isOnline") is True
                    else "Not online (the API does not distinguish Sleeping from Offline)"
                ),
                "lastSeen": device.get("last_seen"),
            }
        )

    return {
        "status": "ok",
        "route": "TeamViewer MCP only",
        "group": {"id": group_id, "name": group.get("name")},
        "deviceCount": len(selected_devices),
        "availabilitySemantics": (
            "TeamViewer returns only an isOnline boolean for company-managed devices. A false "
            "value may be shown as Sleeping or Offline in the TeamViewer UI."
        ),
        "devices": selected_devices,
    }
