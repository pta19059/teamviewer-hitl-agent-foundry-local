import re
import unittest
from pathlib import Path

from teamviewer_hitl.routing import RouteOutcome, route_prompt
from teamviewer_hitl.validation import validate_invocation


_DOCUMENTED_COMMAND = re.compile(r'^teamviewer-hitl "(?P<prompt>.+)"$', re.MULTILINE)


class DocumentedExampleTests(unittest.TestCase):
    def test_operator_example_matrix_routes_to_the_expected_boundary(self) -> None:
        examples = {
            "Hello": (RouteOutcome.CONVERSATION, None, {}, False),
            "Show my TeamViewer account summary.": (RouteOutcome.TOOL, "tv_get_account", {}, False),
            "List the online TeamViewer devices.": (RouteOutcome.HOST, None, {"online_state": "Online"}, False),
            "List the online legacy TeamViewer devices.": (RouteOutcome.TOOL, "tv_list_devices", {"online_state": "Online"}, False),
            "List the online company-managed TeamViewer devices.": (RouteOutcome.TOOL, "tv_list_company_managed_devices", {"online_state": "Online"}, False),
            "Show the devices in SupportGroup.": (RouteOutcome.HOST, None, {"group_name": "SupportGroup"}, False),
            "List all legacy device groups.": (RouteOutcome.TOOL, "tv_list_device_groups", {}, False),
            "List all managed device groups.": (RouteOutcome.TOOL, "tv_list_managed_groups", {}, False),
            "List all TeamViewer sessions.": (RouteOutcome.TOOL, "tv_list_sessions", {}, False),
            "List closed TeamViewer sessions.": (RouteOutcome.TOOL, "tv_list_sessions", {"state": "closed"}, False),
            "Get TeamViewer session code s123.": (RouteOutcome.TOOL, "tv_get_session", {"session_code": "s123"}, False),
            "Get device ID d1234567890.": (RouteOutcome.TOOL, "tv_get_device", {"device_id": "d1234567890"}, False),
            "Show hardware for monitored device with TeamViewer ID 987654321.": (RouteOutcome.TOOL, "tv_get_device_hardware_info", {"teamviewer_id": 987654321}, False),
            "List all connection reports.": (RouteOutcome.TOOL, "tv_list_connection_reports", {}, False),
            "Get connection report ID 550e8400-e29b-41d4-a716-446655440000.": (RouteOutcome.TOOL, "tv_get_connection_report", {"connection_id": "550e8400-e29b-41d4-a716-446655440000"}, False),
            "Show event logs from 2026-08-19T00:00:00Z to 2026-08-20T00:00:00Z.": (RouteOutcome.TOOL, "tv_get_event_logs", {"start_date": "2026-08-19T00:00:00Z", "end_date": "2026-08-20T00:00:00Z"}, False),
            "Create a TeamViewer support session with description HITL-Test in group ID g12345678.": (RouteOutcome.TOOL, "tv_create_session", {"description": "HITL-Test", "groupid": "g12345678"}, True),
            "Update TeamViewer session code s123 with description Customer confirmed.": (RouteOutcome.TOOL, "tv_update_session", {"session_code": "s123", "description": "Customer confirmed"}, True),
            "Close TeamViewer session code s123.": (RouteOutcome.TOOL, "tv_delete_session", {"session_code": "s123"}, True),
            "Set the description of managed device ID 550e8400-e29b-41d4-a716-446655440000 to Lobby kiosk.": (RouteOutcome.TOOL, "tv_update_managed_device_description", {"device_id": "550e8400-e29b-41d4-a716-446655440000", "description": "Lobby kiosk"}, True),
            "Activate monitoring on TeamViewer ID 987654321.": (RouteOutcome.TOOL, "tv_activate_monitoring", {"teamviewer_id": 987654321}, True),
            "Update connection report ID 550e8400-e29b-41d4-a716-446655440000 with notes Reviewed.": (RouteOutcome.TOOL, "tv_update_connection_report", {"connection_id": "550e8400-e29b-41d4-a716-446655440000", "notes": "Reviewed"}, True),
        }

        for prompt, expected in examples.items():
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertEqual(
                    (route.outcome, route.tool_name, dict(route.arguments), route.mutating),
                    expected,
                )

    def test_every_documented_one_shot_prompt_is_routable_and_host_bound(self) -> None:
        readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
        prompts = {
            match.group("prompt")
            .replace("<GROUP_ID>", "g12345678")
            .replace("<EXACT_GROUP_NAME>", "SupportGroup")
            for match in _DOCUMENTED_COMMAND.finditer(readme)
        }
        self.assertTrue(prompts)

        for prompt in sorted(prompts):
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertNotEqual(route.outcome, RouteOutcome.CLARIFY)
                if route.outcome != RouteOutcome.TOOL:
                    continue
                self.assertIsNotNone(route.tool_name)
                self.assertIsNone(
                    validate_invocation(
                        route,
                        prompt,
                        route.tool_name or "",
                        dict(route.arguments),
                    )
                )


if __name__ == "__main__":
    unittest.main()
