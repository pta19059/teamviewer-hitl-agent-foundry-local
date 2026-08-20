import os
import unittest
from pathlib import Path
from unittest.mock import patch

from teamviewer_hitl.config import ConfigurationError, Settings


_TEAMVIEWER_LOCAL_ENV = {
    "TEAMVIEWER_MCP_TRANSPORT": "local",
    "TEAMVIEWER_MCP_SCRIPT": "external/TV_Remote_MCP/dist/index.js",
    "TEAMVIEWER_API_TOKEN": "test-token",
}


class SettingsTests(unittest.TestCase):
    @patch.object(Path, "is_file", return_value=True)
    def test_foundry_local_does_not_require_cloud_settings(self, _is_file) -> None:
        env = {
            **_TEAMVIEWER_LOCAL_ENV,
            "MODEL_PROVIDER": "foundry_local",
            "FOUNDRY_LOCAL_MODEL": "qwen2.5-7b",
            # Keep this unit test independent from a developer's local .env override.
            "FOUNDRY_LOCAL_ENDPOINT": "",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.model_provider, "foundry_local")
        self.assertEqual(settings.foundry_local_model, "qwen2.5-7b")
        self.assertIsNone(settings.foundry_local_endpoint)
        self.assertIsNone(settings.foundry_project_endpoint)

    @patch.object(Path, "is_file", return_value=True)
    def test_cloud_provider_requires_and_loads_project_settings(self, _is_file) -> None:
        env = {
            **_TEAMVIEWER_LOCAL_ENV,
            "MODEL_PROVIDER": "foundry_cloud",
            "FOUNDRY_PROJECT_ENDPOINT": "https://example.test/api/projects/demo",
            "FOUNDRY_MODEL": "deployment",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.model_provider, "foundry_cloud")
        self.assertEqual(settings.foundry_model, "deployment")
        self.assertIsNone(settings.foundry_local_model)

    def test_unknown_model_provider_is_rejected(self) -> None:
        with patch.dict(os.environ, {"MODEL_PROVIDER": "mystery"}, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
