import unittest

from teamviewer_hitl.routing import RouteOutcome, route_prompt


class RoutingTests(unittest.TestCase):
    def assert_tool(self, prompt: str, expected: str, *, mutating: bool = False) -> None:
        route = route_prompt(prompt)
        self.assertEqual(route.outcome, RouteOutcome.TOOL, prompt)
        self.assertEqual(route.tool_name, expected, prompt)
        self.assertEqual(route.mutating, mutating, prompt)

    def test_non_operational_and_informational_prompts_use_no_tool(self) -> None:
        for prompt in (
            "Hello",
            "Thanks for your help",
            "How would I create a TeamViewer session?",
            "Do not create a TeamViewer session.",
            "Explain how to list TeamViewer devices.",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(route_prompt(prompt).outcome, RouteOutcome.CONVERSATION)

    def test_read_adjectives_and_preamble_do_not_become_writes(self) -> None:
        self.assert_tool("List open TeamViewer sessions.", "tv_list_sessions")
        self.assert_tool("Show open sessions.", "tv_list_sessions")
        self.assert_tool("Start by listing monitoring alarms.", "tv_list_monitoring_alarms")

    def test_all_supported_write_intents_have_exact_routes(self) -> None:
        cases = {
            (
                "Create a TeamViewer support session named HITL-Test in group ID g12345678."
            ): "tv_create_session",
            (
                "Update TeamViewer session code s123 description to Escalated case."
            ): "tv_update_session",
            "Close TeamViewer session code s123.": "tv_delete_session",
            (
                "Update managed device ID 550e8400-e29b-41d4-a716-446655440000 "
                "description to Lobby kiosk."
            ): "tv_update_managed_device_description",
            "Activate monitoring on TeamViewer ID 987654321.": "tv_activate_monitoring",
            (
                "Update connection report ID 550e8400-e29b-41d4-a716-446655440000 "
                "with notes Reviewed."
            ): "tv_update_connection_report",
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assert_tool(prompt, expected, mutating=True)

    def test_create_session_requires_exactly_one_legacy_group_selector(self) -> None:
        for prompt in (
            "Create a TeamViewer support session named HITL-Test.",
            "Create a TeamViewer support session named HITL-Test in group Support.",
            "Create a TeamViewer support session named HITL-Test in group name Support.",
            "Create a TeamViewer support session named HITL-Test in group ID invalid.",
            (
                "Create a TeamViewer support session named HITL-Test in group ID "
                "g12345678 and in group ID g87654321."
            ),
            (
                "Create a TeamViewer support session named HITL-Test in group ID "
                "g12345678 and group ID g87654321."
            ),
            (
                "Create a TeamViewer support session named HITL-Test in group ID "
                "g12345678 and group name Support."
            ),
            (
                "Create a TeamViewer support session named HITL-Test in group ID "
                "g12345678 or g87654321."
            ),
            (
                "Create a TeamViewer support session named HITL-Test in group ID "
                "g12345678, g87654321."
            ),
            "Use only tv_create_session with description HITL-Test.",
        ):
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
                self.assertIsNone(route.tool_name)
                self.assertIn("exactly one existing legacy", route.message or "")

    def test_create_session_requires_one_explicit_description(self) -> None:
        for prompt in (
            "Create a TeamViewer support session in group ID g12345678.",
            (
                "Create a TeamViewer support session named First with description Second "
                "in group ID g12345678."
            ),
        ):
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
                self.assertIsNone(route.tool_name)
                self.assertIn("exactly one explicit description", route.message or "")

    def test_supported_write_routes_do_not_depend_on_word_order(self) -> None:
        cases = {
            "For TeamViewer session code s123, close it.": "tv_delete_session",
            (
                "Set the description of managed device ID "
                "550e8400-e29b-41d4-a716-446655440000 to Lab."
            ): "tv_update_managed_device_description",
            (
                "For TeamViewer session code s123, update description to Escalated case."
            ): "tv_update_session",
            "Turn on monitoring for TeamViewer ID 987654321.": "tv_activate_monitoring",
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assert_tool(prompt, expected, mutating=True)

    def test_policy_assignments_fail_closed(self) -> None:
        for prompt in (
            "Assign monitoring policy p1 to device d1.",
            "Apply patch management policy p2 to device d2.",
            "Use only tv_assign_monitoring_policy.",
        ):
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
                self.assertIsNone(route.tool_name)

    def test_previous_misroutes_now_select_exact_read_tools(self) -> None:
        cases = {
            "Show my account summary.": "tv_get_account",
            "Show the company license.": "tv_get_company_license",
            "Show company-managed online devices.": "tv_list_company_managed_devices",
            "Show the devices in SupportGroup.": "tv_list_devices_in_group",
            "List all TeamViewer sessions.": "tv_list_sessions",
            "List monitoring alarms.": "tv_list_monitoring_alarms",
            "List connection reports.": "tv_list_connection_reports",
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assert_tool(prompt, expected)

    def test_explicit_allowed_tool_is_supported(self) -> None:
        self.assert_tool("Use only tv_get_account.", "tv_get_account")

    def test_explicit_unknown_tool_fails_closed(self) -> None:
        route = route_prompt("Use only tv_delete_user.")
        self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
        self.assertIsNone(route.tool_name)

    def test_unsupported_writes_never_fall_through_to_reads(self) -> None:
        for prompt in (
            "Delete connection report c123.",
            "Delete managed group g123.",
            "Create a device group named Finance.",
            "Update my TeamViewer account email.",
            "Close monitoring alarm a123.",
        ):
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
                self.assertIsNone(route.tool_name)

    def test_informational_explicit_write_tool_uses_no_tool(self) -> None:
        route = route_prompt("Please explain how to use tv_delete_session.")
        self.assertEqual(route.outcome, RouteOutcome.CONVERSATION)
        self.assertIsNone(route.tool_name)

    def test_additional_read_word_orders_are_deterministic(self) -> None:
        cases = {
            "List devices belonging to SupportGroup.": "tv_list_devices_in_group",
            "List SupportGroup devices.": "tv_list_devices_in_group",
            (
                "Which groups contain managed device ID "
                "550e8400-e29b-41d4-a716-446655440000?"
            ): "tv_get_managed_device_groups",
            "Show monitored devices.": "tv_list_monitoring_devices",
            (
                "Show hardware for monitored device with TeamViewer ID 987654321."
            ): "tv_get_device_hardware_info",
            (
                "Show system information for monitored device with TeamViewer ID 987654321."
            ): "tv_get_device_system_info",
            (
                "Show software for monitored device with TeamViewer ID 987654321."
            ): "tv_get_device_software_info",
            "Show devices in group ID g12345678.": "tv_list_devices",
            "List managed device groups.": "tv_list_managed_groups",
            "Show open TeamViewer session.": "tv_list_sessions",
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assert_tool(prompt, expected)

        group_route = route_prompt("Show the devices in SupportGroup.")
        self.assertEqual(dict(group_route.arguments), {"group_name": "SupportGroup"})

    def test_multiple_state_changes_require_clarification(self) -> None:
        route = route_prompt(
            "Create a TeamViewer session and close TeamViewer session s123."
        )
        self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
        self.assertIsNone(route.tool_name)

    def test_mixed_and_multi_target_operations_require_clarification(self) -> None:
        prompts = (
            "Create a TeamViewer session with description X and send a chat message.",
            "Close session code s1 and delete user ID u1.",
            "Close session code s1 and list devices.",
            "Close sessions with session code s1 and session code s2.",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
                self.assertIsNone(route.tool_name)

    def test_unsupported_or_ambiguous_write_fields_fail_closed(self) -> None:
        prompts = (
            "Update TeamViewer session code s123 notes to Reviewed.",
            (
                "Create a TeamViewer session with description X and notes Y "
                "in group ID g12345678."
            ),
            (
                "Activate monitoring on TeamViewer ID 987654321 with monitoring "
                "policy ID 550e8400-e29b-41d4-a716-446655440000."
            ),
            "Update connection report ID c123 with notes Reviewed.",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
                self.assertIsNone(route.tool_name)

    def test_read_filters_are_bound_or_rejected_instead_of_being_dropped(self) -> None:
        cases = (
            (
                "Show offline company-managed devices.",
                "tv_list_company_managed_devices",
                {"online_state": "Offline"},
            ),
            (
                "Show online devices in group ID g12345678.",
                "tv_list_devices",
                {"groupid": "g12345678", "online_state": "Online"},
            ),
            (
                "List closed TeamViewer sessions.",
                "tv_list_sessions",
                {"state": "closed"},
            ),
        )
        for prompt, tool_name, arguments in cases:
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertEqual(route.tool_name, tool_name)
                self.assertEqual(dict(route.arguments), arguments)

        for prompt in (
            "List sessions with tag closed.",
            "List open and closed TeamViewer sessions.",
            "Show online and offline managed devices.",
            "Use tv_list_sessions with tag closed.",
            "List company-managed devices in group Finance.",
            "Get monitoring alarm ID alarm-1.",
            "Get device report ID 550e8400-e29b-41d4-a716-446655440000.",
        ):
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
                self.assertIsNone(route.tool_name)


if __name__ == "__main__":
    unittest.main()
