import unittest

from teamviewer_hitl.audit import redact


class AuditTests(unittest.TestCase):
    def test_redacts_nested_secrets_without_changing_other_arguments(self) -> None:
        value = {
            "device_id": "abc",
            "nested": {"token": "secret", "Password": "also-secret"},
            "items": [{"authorization": "Bearer nope"}],
        }
        self.assertEqual(
            redact(value),
            {
                "device_id": "abc",
                "nested": {"token": "[REDACTED]", "Password": "[REDACTED]"},
                "items": [{"authorization": "[REDACTED]"}],
            },
        )


if __name__ == "__main__":
    unittest.main()
