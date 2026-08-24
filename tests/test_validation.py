import unittest

from pydantic import BaseModel

from teamviewer_hitl.policy import APPROVAL_REQUIRED_TOOLS, READ_ONLY_TOOLS
from teamviewer_hitl.routing import RouteOutcome, route_prompt
from teamviewer_hitl.validation import (
    _READ_CONTRACTS,
    _WRITE_CONTRACTS,
    arguments_to_dict,
    validate_invocation,
)


class _Arguments(BaseModel):
    session_code: str
    notes: str | None = None


class ValidationTests(unittest.TestCase):
    def test_every_documented_operational_example_has_valid_host_bound_arguments(self) -> None:
        prompts = (
            "Show my TeamViewer account summary.",
            "List the online legacy TeamViewer devices.",
            "List the online company-managed TeamViewer devices.",
            "List all legacy device groups.",
            "List all managed device groups.",
            "List all TeamViewer sessions.",
            "List closed TeamViewer sessions.",
            "Get TeamViewer session code s123.",
            "Get device ID d1234567890.",
            "Get device ID 550e8400-e29b-41d4-a716-446655440000.",
            "Show hardware for monitored device with TeamViewer ID 987 654 321.",
            "List all connection reports.",
            (
                "Get connection report ID "
                "550e8400-e29b-41d4-a716-446655440000."
            ),
            (
                "Show event logs from 2026-08-19T00:00:00Z "
                "to 2026-08-20T00:00:00Z."
            ),
            (
                "Create a TeamViewer support session with description HITL-Test "
                "in group ID g12345678."
            ),
            "Update TeamViewer session code s123 with description Customer confirmed.",
            "Close TeamViewer session code s123.",
            (
                "Set the description of managed device ID "
                "550e8400-e29b-41d4-a716-446655440000 to Lobby kiosk."
            ),
            "Activate monitoring on TeamViewer ID 987654321.",
            (
                "Update connection report ID "
                "550e8400-e29b-41d4-a716-446655440000 with notes Reviewed."
            ),
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                route = route_prompt(prompt)
                self.assertEqual(route.outcome, RouteOutcome.TOOL)
                self.assertIsNotNone(route.tool_name)
                self.assertIsNone(
                    validate_invocation(
                        route,
                        prompt,
                        route.tool_name or "",
                        dict(route.arguments),
                    )
                )

    def test_every_exposed_tool_has_exactly_one_host_contract(self) -> None:
        self.assertEqual(set(_READ_CONTRACTS), set(READ_ONLY_TOOLS))
        self.assertEqual(set(_WRITE_CONTRACTS), set(APPROVAL_REQUIRED_TOOLS))
        self.assertTrue(set(_READ_CONTRACTS).isdisjoint(_WRITE_CONTRACTS))

    def test_every_documented_write_prompt_and_argument_set_is_executable(self) -> None:
        cases = (
            (
                "Create a TeamViewer support session with description HITL-Test "
                "in group ID g12345678.",
                "tv_create_session",
                {"description": "HITL-Test", "groupid": "g12345678"},
            ),
            (
                "Update TeamViewer session code s123 with description Customer confirmed.",
                "tv_update_session",
                {"session_code": "s123", "description": "Customer confirmed"},
            ),
            (
                "Close TeamViewer session code s123.",
                "tv_delete_session",
                {"session_code": "s123"},
            ),
            (
                "Set the description of managed device ID "
                "550e8400-e29b-41d4-a716-446655440000 to Lobby kiosk.",
                "tv_update_managed_device_description",
                {
                    "device_id": "550e8400-e29b-41d4-a716-446655440000",
                    "description": "Lobby kiosk",
                },
            ),
            (
                "Activate monitoring on TeamViewer ID 987654321.",
                "tv_activate_monitoring",
                {"teamviewer_id": 987654321},
            ),
            (
                "Update connection report ID 550e8400-e29b-41d4-a716-446655440000 "
                "with notes Reviewed.",
                "tv_update_connection_report",
                {
                    "connection_id": "550e8400-e29b-41d4-a716-446655440000",
                    "notes": "Reviewed",
                },
            ),
        )
        for prompt, function_name, arguments in cases:
            with self.subTest(function_name=function_name):
                route = route_prompt(prompt)
                self.assertEqual(route.tool_name, function_name)
                self.assertIsNone(
                    validate_invocation(route, prompt, function_name, arguments)
                )

    def test_pydantic_arguments_are_normalized(self) -> None:
        self.assertEqual(
            arguments_to_dict(_Arguments(session_code="s123")),
            {"session_code": "s123"},
        )

    def test_invalid_json_arguments_become_empty(self) -> None:
        self.assertEqual(arguments_to_dict("not-json"), {})

    def test_wrong_tool_is_blocked(self) -> None:
        route = route_prompt("Close TeamViewer session code s123.")
        error = validate_invocation(
            route,
            "Close TeamViewer session code s123.",
            "tv_activate_monitoring",
            {"teamviewer_id": 987654321},
        )
        self.assertIn("does not match", error or "")

    def test_model_invented_identifier_is_blocked(self) -> None:
        prompt = "Close TeamViewer session code s123."
        route = route_prompt(prompt)
        error = validate_invocation(
            route,
            prompt,
            "tv_delete_session",
            {"session_code": "s999"},
        )
        self.assertIn("does not match", error or "")

    def test_user_supplied_session_update_is_allowed(self) -> None:
        prompt = (
            "Update TeamViewer session code s123 with description Customer confirmed."
        )
        route = route_prompt(prompt)
        self.assertIsNone(
            validate_invocation(
                route,
                prompt,
                "tv_update_session",
                {"session_code": "s123", "description": "Customer confirmed"},
            )
        )

    def test_no_op_session_update_is_blocked(self) -> None:
        prompt = "Update TeamViewer session code s123 with description Escalated case."
        route = route_prompt(prompt)
        error = validate_invocation(
            route, prompt, "tv_update_session", {"session_code": "s123"}
        )
        self.assertIn("Missing required argument(s): description", error or "")

    def test_empty_session_creation_is_blocked(self) -> None:
        prompt = (
            "Create a TeamViewer support session with description HITL-Test "
            "in group ID g12345678."
        )
        route = route_prompt(prompt)
        error = validate_invocation(
            route, prompt, "tv_create_session", {"groupid": "g12345678"}
        )
        self.assertIn("Missing required argument(s): description", error or "")

    def test_invented_mutable_text_is_blocked(self) -> None:
        prompt = (
            "Create a TeamViewer session named HITL-Test in group ID g12345678."
        )
        route = route_prompt(prompt)
        error = validate_invocation(
            route,
            prompt,
            "tv_create_session",
            {
                "description": "A different description",
                "groupid": "g12345678",
            },
        )
        self.assertIn("explicit request field", error or "")

    def test_create_session_description_cannot_reuse_group_id(self) -> None:
        prompt = (
            "Create a TeamViewer support session with description HITL-Test "
            "in group ID g12345678."
        )
        error = validate_invocation(
            route_prompt(prompt),
            prompt,
            "tv_create_session",
            {"description": "g12345678", "groupid": "g12345678"},
        )
        self.assertIn("explicit request field", error or "")

    def test_write_values_cannot_be_reused_from_a_different_field(self) -> None:
        cases = (
            (
                "Update TeamViewer session code s123 with description Customer confirmed.",
                "tv_update_session",
                {"session_code": "s123", "description": "s123"},
            ),
            (
                "Set the description of managed device ID "
                "550e8400-e29b-41d4-a716-446655440000 to Lobby kiosk.",
                "tv_update_managed_device_description",
                {
                    "device_id": "550e8400-e29b-41d4-a716-446655440000",
                    "description": "550e8400-e29b-41d4-a716-446655440000",
                },
            ),
            (
                "Update connection report ID 550e8400-e29b-41d4-a716-446655440000 "
                "with notes Reviewed.",
                "tv_update_connection_report",
                {
                    "connection_id": "550e8400-e29b-41d4-a716-446655440000",
                    "notes": "550e8400-e29b-41d4-a716-446655440000",
                },
            ),
        )
        for prompt, function_name, arguments in cases:
            with self.subTest(function_name=function_name):
                error = validate_invocation(
                    route_prompt(prompt), prompt, function_name, arguments
                )
                self.assertIn("explicit request field", error or "")

    def test_create_session_requires_group_argument_before_approval(self) -> None:
        prompt = (
            "Create a TeamViewer session with description HITL-Test "
            "in group ID g12345678."
        )
        route = route_prompt(prompt)
        error = validate_invocation(
            route,
            prompt,
            "tv_create_session",
            {"description": "HITL-Test"},
        )
        self.assertIn("Missing required argument(s): groupid", error or "")

    def test_create_session_rejects_invented_group_id(self) -> None:
        prompt = (
            "Create a TeamViewer session with description HITL-Test "
            "in group ID g12345678."
        )
        route = route_prompt(prompt)
        invented = validate_invocation(
            route,
            prompt,
            "tv_create_session",
            {"description": "HITL-Test", "groupid": "g87654321"},
        )
        self.assertIn("explicit request field", invented or "")

    def test_create_session_rejects_non_selector_value_later_in_prompt(self) -> None:
        prompt = (
            "Create a TeamViewer session with description HITL-Test "
            "in group ID g12345678 and notes g87654321."
        )
        route = route_prompt(prompt)
        self.assertEqual(route.outcome.value, "clarify")
        self.assertIsNone(route.tool_name)
        self.assertIn("exactly one existing legacy", route.message or "")

    def test_invalid_managed_device_uuid_is_blocked(self) -> None:
        prompt = "Update managed device d1 description to Kiosk."
        route = route_prompt(prompt)
        self.assertEqual(route.outcome.value, "clarify")
        self.assertIsNone(route.tool_name)

    def test_positive_user_supplied_teamviewer_id_is_allowed(self) -> None:
        prompt = "Activate monitoring on TeamViewer ID 987654321."
        route = route_prompt(prompt)
        self.assertIsNone(
            validate_invocation(
                route,
                prompt,
                "tv_activate_monitoring",
                {"teamviewer_id": 987654321},
            )
        )

    def test_connection_report_update_requires_notes(self) -> None:
        prompt = (
            "Update connection report ID 550e8400-e29b-41d4-a716-446655440000 "
            "with notes Reviewed."
        )
        route = route_prompt(prompt)
        error = validate_invocation(
            route,
            prompt,
            "tv_update_connection_report",
            {"connection_id": "550e8400-e29b-41d4-a716-446655440000"},
        )
        self.assertIn("Missing required argument(s): notes", error or "")

    def test_identifier_substrings_are_not_provenance(self) -> None:
        prompt = "Close TeamViewer session code s123."
        route = route_prompt(prompt)
        error = validate_invocation(
            route, prompt, "tv_delete_session", {"session_code": "s1"}
        )
        self.assertIn("explicit request field", error or "")

    def test_numeric_session_id_proves_canonical_prefixed_code(self) -> None:
        prompt = (
            "Update TeamViewer session code 156827066 with description Customer confirmed."
        )
        route = route_prompt(prompt)

        self.assertIsNone(
            validate_invocation(
                route,
                prompt,
                "tv_update_session",
                {
                    "session_code": "s156827066",
                    "description": "Customer confirmed",
                },
            )
        )

    def test_numeric_identifier_substrings_are_not_provenance(self) -> None:
        prompt = "Activate monitoring on TeamViewer ID 987654321."
        route = route_prompt(prompt)
        error = validate_invocation(
            route, prompt, "tv_activate_monitoring", {"teamviewer_id": 1}
        )
        self.assertIn("explicit request field", error or "")

    def test_name_cannot_masquerade_as_session_code(self) -> None:
        prompt = "Close support session named HITL-Test."
        route = route_prompt(prompt)
        self.assertEqual(route.outcome.value, "clarify")
        self.assertIsNone(route.tool_name)

    def test_unknown_argument_is_rejected(self) -> None:
        prompt = "Show my account summary."
        route = route_prompt(prompt)
        error = validate_invocation(route, prompt, "tv_get_account", {"scope": "all"})
        self.assertIn("Unsupported argument", error or "")

    def test_required_read_identifier_cannot_be_missing(self) -> None:
        prompt = "Get the TeamViewer session."
        route = route_prompt(prompt)
        error = validate_invocation(route, prompt, "tv_get_session", {})
        self.assertIn("session_code", error or "")

    def test_read_identifier_requires_exact_label_and_value(self) -> None:
        prompt = "Get device ID d1234567890."
        route = route_prompt(prompt)
        self.assertIsNone(
            validate_invocation(
                route, prompt, "tv_get_device", {"device_id": "d1234567890"}
            )
        )

    def test_managed_device_read_requires_canonical_uuid(self) -> None:
        prompt = "Get managed device ID not-a-uuid."
        route = route_prompt(prompt)
        self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
        self.assertIn("canonical", route.message or "")

    def test_relative_date_cannot_authorize_invented_absolute_dates(self) -> None:
        prompt = "Show TeamViewer event logs for yesterday."
        route = route_prompt(prompt)
        self.assertEqual(route.outcome, RouteOutcome.CLARIFY)
        self.assertIn("ISO 8601", route.message or "")

    def test_explicit_iso_date_range_is_allowed(self) -> None:
        prompt = (
            "Show TeamViewer event logs from 2026-08-19T00:00:00Z "
            "to 2026-08-20T00:00:00Z."
        )
        route = route_prompt(prompt)
        self.assertIsNone(
            validate_invocation(
                route,
                prompt,
                "tv_get_event_logs",
                {
                    "start_date": "2026-08-19T00:00:00Z",
                    "end_date": "2026-08-20T00:00:00Z",
                },
            )
        )

    def test_host_owned_pagination_argument_is_rejected(self) -> None:
        prompt = "List company-managed devices with pagination token secret-token."
        route = route_prompt(prompt)
        error = validate_invocation(
            route,
            prompt,
            "tv_list_company_managed_devices",
            {"pagination_token": "secret-token"},
        )
        self.assertIn("Unsupported argument", error or "")

    def test_unrequested_read_filter_is_rejected_even_when_false(self) -> None:
        prompt = "List company-managed devices."
        error = validate_invocation(
            route_prompt(prompt),
            prompt,
            "tv_list_company_managed_devices",
            {"online_state": "Offline"},
        )
        self.assertIn("not explicitly requested", error or "")

    def test_requested_read_filter_must_match_the_exact_route(self) -> None:
        prompt = "Show online devices in group ID g12345678."
        error = validate_invocation(
            route_prompt(prompt),
            prompt,
            "tv_list_devices",
            {"groupid": "g12345678", "online_state": "Offline"},
        )
        self.assertIn("does not match", error or "")

    def test_inventory_read_requires_numeric_teamviewer_id(self) -> None:
        prompt = "Show hardware for monitored device with TeamViewer ID 987654321."
        route = route_prompt(prompt)
        self.assertIsNone(
            validate_invocation(
                route,
                prompt,
                "tv_get_device_hardware_info",
                {"teamviewer_id": 987654321},
            )
        )
        error = validate_invocation(
            route,
            prompt,
            "tv_get_device_hardware_info",
            {"teamviewer_id": "987654321"},
        )
        self.assertIn("does not match", error or "")

    def test_device_name_prefix_is_bound_and_cannot_be_changed(self) -> None:
        prompt = "List online company-managed TeamViewer devices starting with p."
        route = route_prompt(prompt)
        self.assertIsNone(
            validate_invocation(
                route,
                prompt,
                "tv_list_company_managed_devices",
                {"online_state": "Online", "name_prefix": "p"},
            )
        )
        self.assertIn(
            "does not match",
            validate_invocation(
                route,
                prompt,
                "tv_list_company_managed_devices",
                {"online_state": "Online", "name_prefix": "x"},
            )
            or "",
        )

    def test_event_log_date_fields_cannot_be_swapped(self) -> None:
        prompt = (
            "Show TeamViewer event logs from 2026-08-19T00:00:00Z "
            "to 2026-08-20T00:00:00Z."
        )
        error = validate_invocation(
            route_prompt(prompt),
            prompt,
            "tv_get_event_logs",
            {
                "start_date": "2026-08-20T00:00:00Z",
                "end_date": "2026-08-19T00:00:00Z",
            },
        )
        self.assertIn("does not match", error or "")

if __name__ == "__main__":
    unittest.main()
