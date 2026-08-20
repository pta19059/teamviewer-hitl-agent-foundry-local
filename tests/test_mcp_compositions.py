import json
import unittest
from types import SimpleNamespace

from teamviewer_hitl.mcp_compositions import list_devices_in_managed_group


class _FakeMCP:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def call_tool(self, name, **arguments):
        self.calls.append((name, arguments))
        payload = next(self.responses)
        return [SimpleNamespace(text=json.dumps(payload))]


class TeamViewerManagedGroupMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_group_and_verifies_each_device_membership_via_mcp(self) -> None:
        group_id = "db89eed2-90df-403c-903c-94a1d765567a"
        mcp = _FakeMCP(
            [
                {"resources": [{"id": group_id, "name": "StefanoGroup"}]},
                {
                    "resources": [
                        {
                            "id": "device-1",
                            "teamviewerId": 765084609,
                            "name": "2219400-STEFANO",
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
                {"resources": [{"id": group_id, "name": "StefanoGroup"}]},
                {"resources": [{"id": "another-group", "name": "OtherGroup"}]},
            ]
        )

        result = await list_devices_in_managed_group(mcp, "stefanogroup")

        self.assertEqual(result["route"], "TeamViewer MCP only")
        self.assertEqual(result["deviceCount"], 1)
        self.assertEqual(result["devices"][0]["name"], "2219400-STEFANO")
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

        result = await list_devices_in_managed_group(mcp, "StefanoGroup")

        self.assertEqual(result["status"], "not_found")
        self.assertEqual([name for name, _ in mcp.calls], ["tv_list_managed_groups"])

    async def test_rejects_ambiguous_exact_group_names(self) -> None:
        mcp = _FakeMCP(
            [
                {
                    "resources": [
                        {"id": "group-1", "name": "StefanoGroup"},
                        {"id": "group-2", "name": "StefanoGroup"},
                    ]
                }
            ]
        )

        result = await list_devices_in_managed_group(mcp, "StefanoGroup")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["matches"]), 2)

    async def test_company_device_listing_follows_mcp_pagination_token(self) -> None:
        group_id = "group-1"
        mcp = _FakeMCP(
            [
                {"resources": [{"id": group_id, "name": "StefanoGroup"}]},
                {
                    "resources": [{"id": "device-1", "name": "One"}],
                    "nextPaginationToken": "next-page",
                },
                {"resources": [{"id": "device-2", "name": "Two"}]},
                {"resources": [{"id": group_id}]},
                {"resources": [{"id": group_id}]},
            ]
        )

        result = await list_devices_in_managed_group(mcp, "StefanoGroup")

        self.assertEqual(result["deviceCount"], 2)
        self.assertEqual(
            mcp.calls[2],
            ("tv_list_company_managed_devices", {"pagination_token": "next-page"}),
        )


if __name__ == "__main__":
    unittest.main()
