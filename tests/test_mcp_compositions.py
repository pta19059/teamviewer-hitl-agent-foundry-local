import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from teamviewer_hitl.mcp_compositions import (
    TeamViewerMCPReadError,
    list_devices_across_namespaces,
    list_devices_in_group,
    list_devices_in_managed_group,
)


class _FakeMCP:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def call_tool(self, name, **arguments):
        self.calls.append((name, arguments))
        payload = next(self.responses)
        if isinstance(payload, Exception):
            raise payload
        return [SimpleNamespace(text=json.dumps(payload))]


class TeamViewerManagedGroupMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_group_and_verifies_each_device_membership_via_mcp(self) -> None:
        group_id = "db89eed2-90df-403c-903c-94a1d765567a"
        mcp = _FakeMCP(
            [
                {"resources": [{"id": group_id, "name": "SupportGroup"}]},
                {
                    "resources": [
                        {
                            "id": "device-1",
                            "teamviewerId": 987654321,
                            "name": "Support-Laptop",
                            "isOnline": True,
                        },
                        {
                            "id": "device-2",
                            "teamviewerId": 999,
                            "name": "Other device",
                            "isOnline": False,
                        },
                    ]
                },
                {"resources": [{"id": group_id, "name": "SupportGroup"}]},
                {"resources": [{"id": "another-group", "name": "OtherGroup"}]},
            ]
        )

        result = await list_devices_in_managed_group(mcp, "supportgroup")

        self.assertEqual(result["route"], "TeamViewer MCP only")
        self.assertEqual(result["deviceCount"], 1)
        self.assertEqual(result["devices"][0]["name"], "Support-Laptop")
        self.assertEqual(
            [name for name, _ in mcp.calls],
            [
                "tv_list_managed_groups",
                "tv_list_company_managed_devices",
                "tv_get_managed_device_groups",
                "tv_get_managed_device_groups",
            ],
        )

    async def test_not_found_stops_after_managed_group_mcp_call(self) -> None:
        mcp = _FakeMCP([{"resources": [{"id": "other", "name": "OtherGroup"}]}])

        result = await list_devices_in_managed_group(mcp, "SupportGroup")

        self.assertEqual(result["status"], "not_found")
        self.assertEqual([name for name, _ in mcp.calls], ["tv_list_managed_groups"])

    async def test_rejects_ambiguous_exact_group_names(self) -> None:
        mcp = _FakeMCP(
            [
                {
                    "resources": [
                        {"id": "group-1", "name": "SupportGroup"},
                        {"id": "group-2", "name": "SupportGroup"},
                    ]
                }
            ]
        )

        result = await list_devices_in_managed_group(mcp, "SupportGroup")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["matches"]), 2)

    async def test_company_device_listing_follows_mcp_pagination_token(self) -> None:
        group_id = "group-1"
        mcp = _FakeMCP(
            [
                {"resources": [{"id": group_id, "name": "SupportGroup"}]},
                {
                    "resources": [{"id": "device-1", "name": "One"}],
                    "nextPaginationToken": "next-page",
                },
                {"resources": [{"id": "device-2", "name": "Two"}]},
                {"resources": [{"id": group_id}]},
                {"resources": [{"id": group_id}]},
            ]
        )

        result = await list_devices_in_managed_group(mcp, "SupportGroup")

        self.assertEqual(result["deviceCount"], 2)
        self.assertEqual(
            mcp.calls[2],
            ("tv_list_company_managed_devices", {"pagination_token": "next-page"}),
        )

    async def test_transient_membership_failure_is_retried_and_recovers(self) -> None:
        group_id = "group-1"
        mcp = _FakeMCP(
            [
                {"resources": [{"id": group_id, "name": "SupportGroup"}]},
                {"resources": [{"id": "device-1", "name": "Laptop"}]},
                TimeoutError("temporary"),
                {"resources": [{"id": group_id}]},
            ]
        )

        with patch(
            "teamviewer_hitl.mcp_compositions.asyncio.sleep", new_callable=AsyncMock
        ):
            result = await list_devices_in_managed_group(mcp, "SupportGroup")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["deviceCount"], 1)
        self.assertEqual(
            [name for name, _ in mcp.calls].count("tv_get_managed_device_groups"),
            2,
        )

    async def test_exhausted_membership_retry_returns_explicit_partial_result(self) -> None:
        group_id = "group-1"
        sensitive_message = "TEAMVIEWER_API_TOKEN=do-not-display"
        mcp = _FakeMCP(
            [
                {"resources": [{"id": group_id, "name": "SupportGroup"}]},
                {
                    "resources": [
                        {"id": "device-1", "name": "Unavailable Laptop"},
                        {"id": "device-2", "name": "Verified Laptop"},
                    ]
                },
                RuntimeError(sensitive_message),
                RuntimeError(sensitive_message),
                RuntimeError(sensitive_message),
                {"resources": [{"id": group_id}]},
            ]
        )

        with patch(
            "teamviewer_hitl.mcp_compositions.asyncio.sleep", new_callable=AsyncMock
        ), self.assertLogs("teamviewer_hitl.mcp_compositions", level="WARNING") as logs:
            result = await list_devices_in_managed_group(mcp, "SupportGroup")

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["deviceCount"], 1)
        self.assertEqual(
            result["failedMembershipChecks"],
            [{"id": "device-1", "name": "Unavailable Laptop"}],
        )
        self.assertNotIn(sensitive_message, "\n".join(logs.output))
        self.assertIn("error_type=RuntimeError", "\n".join(logs.output))


class TeamViewerGroupResolverMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_unique_legacy_group_is_resolved_and_listed_via_mcp(self) -> None:
        mcp = _FakeMCP(
            [
                {"resources": [{"id": "g-finance", "name": "Finance"}]},
                {"resources": []},
                {
                    "resources": [
                        {
                            "device_id": "d1",
                            "alias": "Finance-Laptop",
                            "online_state": "Online",
                        }
                    ]
                },
            ]
        )

        result = await list_devices_in_group(mcp, "Finance")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["groupNamespace"], "legacy")
        self.assertEqual(result["deviceCount"], 1)
        self.assertEqual(
            mcp.calls,
            [
                ("tv_list_device_groups", {}),
                ("tv_list_managed_groups", {}),
                ("tv_list_devices", {"groupid": "g-finance"}),
            ],
        )

    async def test_same_name_across_namespaces_is_reported_as_ambiguous(self) -> None:
        mcp = _FakeMCP(
            [
                {"resources": [{"id": "g1", "name": "Operations"}]},
                {"resources": [{"id": "g2", "name": "Operations"}]},
            ]
        )

        result = await list_devices_in_group(mcp, "Operations")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(
            {match["namespace"] for match in result["matches"]},
            {"legacy", "managed"},
        )
        self.assertEqual(len(mcp.calls), 2)

    async def test_managed_group_name_resolution_fails_on_incomplete_page(self) -> None:
        mcp = _FakeMCP(
            [
                {"resources": []},
                {"resources": [], "nextPaginationToken": "next-page"},
            ]
        )

        with self.assertRaises(TeamViewerMCPReadError):
            await list_devices_in_group(mcp, "Operations")

        self.assertEqual(
            mcp.calls,
            [("tv_list_device_groups", {}), ("tv_list_managed_groups", {})],
        )


class TeamViewerCrossNamespaceInventoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_online_inventory_reads_both_official_namespaces(self) -> None:
        mcp = _FakeMCP(
            [
                {"resources": [{"device_id": "d1", "online_state": "Online"}]},
                {
                    "resources": [
                        {"id": "m1", "isOnline": True},
                        {"id": "m2", "isOnline": False},
                    ]
                },
            ]
        )

        result = await list_devices_across_namespaces(mcp, "Online")

        self.assertEqual(len(result["legacyDevices"]), 1)
        self.assertEqual([item["id"] for item in result["managedDevices"]], ["m1"])
        self.assertEqual(
            mcp.calls,
            [
                ("tv_list_devices", {"online_state": "Online"}),
                ("tv_list_company_managed_devices", {}),
            ],
        )

    async def test_cross_namespace_inventory_applies_explicit_name_prefix(self) -> None:
        mcp = _FakeMCP(
            [
                {
                    "resources": [
                        {"device_id": "d1", "alias": "Primary", "online_state": "Online"},
                        {"device_id": "d2", "alias": "Secondary", "online_state": "Online"},
                    ]
                },
                {
                    "resources": [
                        {"id": "m1", "name": "paytons-003", "isOnline": True},
                        {"id": "m2", "name": "robc-02", "isOnline": True},
                    ]
                },
            ]
        )

        result = await list_devices_across_namespaces(mcp, "Online", "p")

        self.assertEqual([item["alias"] for item in result["legacyDevices"]], ["Primary"])
        self.assertEqual([item["name"] for item in result["managedDevices"]], ["paytons-003"])
        self.assertEqual(result["namePrefix"], "p")


if __name__ == "__main__":
    unittest.main()
