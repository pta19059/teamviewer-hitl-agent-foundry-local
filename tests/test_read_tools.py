import json
import unittest
from types import SimpleNamespace

from teamviewer_hitl.mcp_compositions import TeamViewerMCPReadError
from teamviewer_hitl.read_tools import create_mcp_read_tools


class _FakeMCP:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def call_tool(self, name, **arguments):
        self.calls.append((name, arguments))
        payload = next(self.responses)
        return [SimpleNamespace(text=json.dumps(payload))]


class ReadToolTests(unittest.IsolatedAsyncioTestCase):
    def _tool(self, mcp, name):
        tools = {tool.name: tool for tool in create_mcp_read_tools(mcp)}
        return tools[name]

    def test_read_adapters_have_an_exact_non_approving_capability_set(self) -> None:
        mcp = _FakeMCP([])
        tools = {tool.name: tool for tool in create_mcp_read_tools(mcp)}

        self.assertEqual(
            set(tools),
            {
                "tv_list_managed_devices",
                "tv_list_company_managed_devices",
                "tv_list_managed_groups",
                "tv_list_monitoring_alarms",
                "tv_get_device_hardware_info",
                "tv_get_device_system_info",
                "tv_get_device_software_info",
                "tv_list_connection_reports",
                "tv_list_device_reports",
                "tv_get_event_logs",
                "tv_list_sessions",
            },
        )
        self.assertTrue(
            all(tool.approval_mode == "never_require" for tool in tools.values())
        )

    async def test_managed_devices_are_paginated_and_filtered_locally(self) -> None:
        mcp = _FakeMCP(
            [
                {
                    "resources": [
                        {"id": "one", "isOnline": True},
                        {"id": "two", "isOnline": False},
                    ],
                    "nextPaginationToken": "next-page",
                },
                {"resources": [{"id": "three", "isOnline": False}]},
            ]
        )

        result = await self._tool(mcp, "tv_list_managed_devices").func(
            online_state="Offline"
        )

        self.assertEqual([item["id"] for item in result["resources"]], ["two", "three"])
        self.assertEqual(
            mcp.calls,
            [
                ("tv_list_managed_devices", {}),
                ("tv_list_managed_devices", {"pagination_token": "next-page"}),
            ],
        )

    async def test_company_managed_devices_use_the_same_safe_paginator(self) -> None:
        mcp = _FakeMCP([{"resources": [{"id": "one", "isOnline": True}]}])

        result = await self._tool(mcp, "tv_list_company_managed_devices").func(
            online_state="Online"
        )

        self.assertEqual(result["resources"], [{"id": "one", "isOnline": True}])
        self.assertEqual(mcp.calls, [("tv_list_company_managed_devices", {})])

    async def test_report_listing_uses_the_api_uuid_cursor_through_mcp(self) -> None:
        cursor = "550e8400-e29b-41d4-a716-446655440000"
        mcp = _FakeMCP(
            [
                {
                    "records": [{"id": "one"}],
                    "records_remaining": 1,
                    "next_offset": f"https://example.invalid/reports?offset_id={cursor}",
                },
                {"records": [{"id": "two"}], "records_remaining": 0},
            ]
        )

        result = await self._tool(mcp, "tv_list_connection_reports").func()

        self.assertEqual(result["records"], [{"id": "one"}, {"id": "two"}])
        self.assertEqual(
            mcp.calls,
            [
                ("tv_list_connection_reports", {}),
                ("tv_list_connection_reports", {"offset_id": cursor}),
            ],
        )

    async def test_inventory_tools_map_numeric_teamviewer_id_to_mcp_device_id(self) -> None:
        for name in (
            "tv_get_device_hardware_info",
            "tv_get_device_system_info",
            "tv_get_device_software_info",
        ):
            with self.subTest(name=name):
                mcp = _FakeMCP([{"ok": True}])

                await self._tool(mcp, name).func(teamviewer_id=987654321)

                self.assertEqual(mcp.calls, [(name, {"device_id": "987654321"})])

    async def test_monitoring_alarms_follow_the_mcp_continuation_token(self) -> None:
        mcp = _FakeMCP(
            [
                {"Alarms": [{"id": "one"}], "ContinuationToken": "next-page"},
                {"Alarms": [{"id": "two"}]},
            ]
        )

        result = await self._tool(mcp, "tv_list_monitoring_alarms").func()

        self.assertEqual(result["Alarms"], [{"id": "one"}, {"id": "two"}])
        self.assertEqual(
            mcp.calls[1],
            ("tv_list_monitoring_alarms", {"continuation_token": "next-page"}),
        )

    async def test_managed_groups_fail_closed_when_the_mcp_cannot_fetch_next_page(self) -> None:
        mcp = _FakeMCP(
            [{"resources": [], "nextPaginationToken": "unforwardable-token"}]
        )

        with self.assertRaisesRegex(TeamViewerMCPReadError, "cannot forward"):
            await self._tool(mcp, "tv_list_managed_groups").func()

    async def test_event_logs_fail_closed_instead_of_returning_a_partial_page(self) -> None:
        mcp = _FakeMCP([{"Events": [], "PaginationToken": "next-page"}])

        with self.assertRaisesRegex(TeamViewerMCPReadError, "wrong API field"):
            await self._tool(mcp, "tv_get_event_logs").func(
                start_date="2026-08-19T00:00:00Z",
                end_date="2026-08-20T00:00:00Z",
            )

    async def test_sessions_fail_closed_when_more_results_exist(self) -> None:
        mcp = _FakeMCP(
            [{"sessions": [], "sessions_remaining": 1, "next_offset": "1"}]
        )

        with self.assertRaisesRegex(TeamViewerMCPReadError, "offset cursor"):
            await self._tool(mcp, "tv_list_sessions").func(state="open")


if __name__ == "__main__":
    unittest.main()
