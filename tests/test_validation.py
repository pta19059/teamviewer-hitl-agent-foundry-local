import unittest

from pydantic import BaseModel

from teamviewer_hitl.policy import APPROVAL_REQUIRED_TOOLS, READ_ONLY_TOOLS
from teamviewer_hitl.routing import route_prompt
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
    def test_every_exposed_tool_has_exactly_one_host_contract(self) -> None:
        self.assertEqual(set(_READ_CONTRACTS), set(READ_ONLY_TOOLS))
        self.assertEqual(set(_WRITE_CONTRACTS), set(APPROVAL_REQUIRED_TOOLS))
        self.assertTrue(set(_READ_CONTRACTS).isdisjoint(_WRITE_CONTRACTS))

    def test_every_documented_write_prompt_and_argument_set_is_executable(self) -> None:
        cases = (
            (
                "Create a TeamViewer support session with description HITL-Test.",
                "tv_create_session",
                {"description": "HITL-Test"},
            ),
            (
                "Update TeamViewer session code s123 notes to Customer confirmed.",
                "tv_update_session",
                {"session_code": "s123", "notes": "Customer confirmed"},
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
                "Update connection report ID c123 notes to Reviewed.",
                "tv_update_connection_report",
                {"connection_id": "c123", "notes": "Reviewed"},
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
        route = route_prompt("Close the TeamViewer session.")
        error = validate_invocation(
            route,
            "Close the TeamViewer session.",
            "tv_delete_session",
            {"session_code": "s123"},
        )
        self.assertIn("explicit identifier label", error or "")

    def test_user_supplied_session_update_is_allowed(self) -> None:
        prompt = "Update TeamViewer session code s123 notes to Customer confirmed."
        route = route_prompt(prompt)
        self.assertIsNone(
            validate_invocation(
                route,
                prompt,
                "tv_update_session",
                {"session_code": "s123", "notes": "Customer confirmed"},
            )
        )

    def test_no_op_session_update_is_blocked(self) -> None:
        prompt = "Update TeamViewer session code s123."
        route = route_prompt(prompt)
        error = validate_invocation(
            route, prompt, "tv_update_session", {"session_code": "s123"}
        )
        self.assertIn("at least one session field", error or "")

    def test_empty_session_creation_is_blocked(self) -> None:
        prompt = "Create a TeamViewer support session."
        route = route_prompt(prompt)
        error = validate_invocation(route, prompt, "tv_create_session", {})
        self.assertIn("Missing required argument(s): description", error or "")

    def test_invented_mutable_text_is_blocked(self) -> None:
        prompt = "Create a TeamViewer session named HITL-Test."
        route = route_prompt(prompt)
        error = validate_invocation(
            route,
            prompt,
            "tv_create_session",
            {"description": "A different description"},
        )
        self.assertIn("explicitly supplied", error or "")

    def test_invalid_managed_device_uuid_is_blocked(self) -> None:
        prompt = "Update managed device d1 description to Kiosk."
        route = route_prompt(prompt)
        error = validate_invocation(
            route,
            prompt,
            "tv_update_managed_device_description",
            {"device_id": "d1", "description": "Kiosk"},
        )
        self.assertIn("explicit identifier label", error or "")

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
        prompt = "Update connection report c123."
        route = route_prompt(prompt)
        error = validate_invocation(
            route, prompt, "tv_update_connection_report", {"connection_id": "c123"}
        )
        self.assertIn("Missing required argument(s): notes", error or "")

    def test_identifier_substrings_are_not_provenance(self) -> None:
        prompt = "Close TeamViewer session code s123."
        route = route_prompt(prompt)
        error = validate_invocation(
            route, prompt, "tv_delete_session", {"session_code": "s1"}
        )
        self.assertIn("explicit identifier label", error or "")

    def test_numeric_identifier_substrings_are_not_provenance(self) -> None:
        prompt = "Activate monitoring on TeamViewer ID 987654321."
        route = route_prompt(prompt)
        error = validate_invocation(
            route, prompt, "tv_activate_monitoring", {"teamviewer_id": 1}
        )
        self.assertIn("explicit identifier label", error or "")

    def test_name_cannot_masquerade_as_session_code(self) -> None:
        prompt = "Close support session named HITL-Test."
        route = route_prompt(prompt)
        error = validate_invocation(
            route, prompt, "tv_delete_session", {"session_code": "HITL-Test"}
        )
        self.assertIn("explicit identifier label", error or "")

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
        error = validate_invocation(
            route,
            prompt,
            "tv_get_managed_device",
            {"device_id": "not-a-uuid"},
        )
        self.assertIn("canonical", error or "")

    def test_relative_date_cannot_authorize_invented_absolute_dates(self) -> None:
        prompt = "Show TeamViewer event logs for yesterday."
        route = route_prompt(prompt)
        error = validate_invocation(
            route,
            prompt,
            "tv_get_event_logs",
            {
                "start_date": "2026-08-19T00:00:00Z",
                "end_date": "2026-08-20T00:00:00Z",
            },
        )
        self.assertIn("must appear exactly", error or "")

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

    def test_group_composition_requires_exact_name_provenance(self) -> None:
        prompt = "Show the devices in StefanoGroup."
        route = route_prompt(prompt)
        error = validate_invocation(
            route,
            prompt,
            "tv_list_devices_in_group",
            {"group_name": "Stefano"},
        )
        self.assertIn("must appear exactly", error or "")

    def test_exact_group_name_is_allowed(self) -> None:
        prompt = "Show devices in managed group StefanoGroup."
        route = route_prompt(prompt)
        self.assertIsNone(
            validate_invocation(
                route,
                prompt,
                "tv_list_devices_in_group",
                {"group_name": "StefanoGroup"},
            )
        )


if __name__ == "__main__":
    unittest.main()
