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


def _collection(
    payload: dict[str, Any], tool_name: str, *keys: str
) -> list[dict[str, Any]]:
    for key in keys:
        values = payload.get(key)
        if isinstance(values, list):
            return [value for value in values if isinstance(value, dict)]
    expected = ", ".join(keys)
    raise TeamViewerMCPReadError(
        f"{tool_name} did not return any expected collection ({expected})"
    )


async def _list_managed_groups(teamviewer: Any) -> list[dict[str, Any]]:
    payload = _decode_mcp_json(
        await teamviewer.call_tool("tv_list_managed_groups"),
        "tv_list_managed_groups",
    )
    groups = _resources(payload, "tv_list_managed_groups")
    if payload.get("nextPaginationToken"):
        # The current official MCP handler advertises and sends limit/offset, while
        # the TeamViewer API requires paginationToken. Returning a partial group set
        # could resolve a name incorrectly, so stop until the upstream tool is fixed.
        raise TeamViewerMCPReadError(
            "The official MCP managed-group tool cannot retrieve the next API page"
        )
    return groups


async def _list_legacy_groups(teamviewer: Any) -> list[dict[str, Any]]:
    payload = _decode_mcp_json(
        await teamviewer.call_tool("tv_list_device_groups"),
        "tv_list_device_groups",
    )
    return _collection(payload, "tv_list_device_groups", "groups", "resources")


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


async def list_devices_across_namespaces(
    teamviewer: Any, online_state: str | None = None
) -> dict[str, Any]:
    """List legacy and company-managed devices through official MCP tools only."""
    if online_state not in {None, "Online", "Offline"}:
        raise TeamViewerMCPReadError("Availability must be Online or Offline")

    legacy_arguments = {"online_state": online_state} if online_state else {}
    legacy_payload = _decode_mcp_json(
        await teamviewer.call_tool("tv_list_devices", **legacy_arguments),
        "tv_list_devices",
    )
    legacy_devices = _collection(
        legacy_payload, "tv_list_devices", "devices", "resources"
    )

    managed_devices = await _list_company_managed_devices(teamviewer)
    if online_state is not None:
        expected = online_state == "Online"
        managed_devices = [
            device for device in managed_devices if device.get("isOnline") is expected
        ]

    return {
        "status": "ok",
        "route": "TeamViewer MCP only",
        "onlineState": online_state,
        "legacyDevices": legacy_devices,
        "managedDevices": managed_devices,
    }


async def _managed_group_result(teamviewer: Any, group: dict[str, Any]) -> dict[str, Any]:
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


async def list_devices_in_managed_group(
    teamviewer: Any, group_name: str
) -> dict[str, Any]:
    """Return exact managed-group membership using only TeamViewer MCP tool calls."""
    requested_name = group_name.strip()
    if not requested_name:
        raise TeamViewerMCPReadError("Managed group name cannot be empty")

    matches = [
        group
        for group in await _list_managed_groups(teamviewer)
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
    return await _managed_group_result(teamviewer, matches[0])


async def list_devices_in_group(
    teamviewer: Any,
    group_name: str,
    group_namespace: str | None = None,
) -> dict[str, Any]:
    """Resolve a legacy or managed group exactly, then list membership through MCP."""
    requested_name = group_name.strip()
    namespace = group_namespace.strip().casefold() if group_namespace else None
    if not requested_name:
        raise TeamViewerMCPReadError("Group name cannot be empty")
    if namespace not in {None, "legacy", "managed"}:
        raise TeamViewerMCPReadError("Group namespace must be legacy or managed")

    matches: list[tuple[str, dict[str, Any]]] = []
    if namespace in {None, "legacy"}:
        matches.extend(
            ("legacy", group)
            for group in await _list_legacy_groups(teamviewer)
            if str(group.get("name", "")).casefold() == requested_name.casefold()
        )
    if namespace in {None, "managed"}:
        matches.extend(
            ("managed", group)
            for group in await _list_managed_groups(teamviewer)
            if str(group.get("name", "")).casefold() == requested_name.casefold()
        )

    if not matches:
        return {
            "status": "not_found",
            "requestedGroupName": requested_name,
            "requestedNamespace": namespace,
            "message": "No TeamViewer group matched the requested name exactly.",
        }
    if len(matches) > 1:
        return {
            "status": "ambiguous",
            "requestedGroupName": requested_name,
            "matches": [
                {
                    "namespace": item_namespace,
                    "id": group.get("id"),
                    "name": group.get("name"),
                }
                for item_namespace, group in matches
            ],
            "message": (
                "More than one legacy or managed group has the requested name. "
                "Specify the group namespace."
            ),
        }

    selected_namespace, group = matches[0]
    if selected_namespace == "managed":
        result = await _managed_group_result(teamviewer, group)
        result["groupNamespace"] = "managed"
        return result

    group_id = str(group.get("id", ""))
    if not group_id:
        raise TeamViewerMCPReadError("TeamViewer MCP returned a legacy group without an ID")
    payload = _decode_mcp_json(
        await teamviewer.call_tool("tv_list_devices", groupid=group_id),
        "tv_list_devices",
    )
    devices = _collection(payload, "tv_list_devices", "devices", "resources")
    return {
        "status": "ok",
        "route": "TeamViewer MCP only",
        "groupNamespace": "legacy",
        "group": {"id": group_id, "name": group.get("name")},
        "deviceCount": len(devices),
        "devices": devices,
    }
