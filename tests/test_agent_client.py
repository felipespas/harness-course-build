import os
import runpy
import unittest
from unittest.mock import Mock, patch


class AgentClientTests(unittest.TestCase):
    def load_agent(self, settings):
        token_provider = Mock(return_value="test-token")
        with (
            patch.dict(os.environ, settings, clear=True),
            patch("dotenv.load_dotenv"),
            patch("azure.identity.DefaultAzureCredential"),
            patch(
                "azure.identity.get_bearer_token_provider",
                return_value=token_provider,
            ) as get_provider,
            patch("openai.OpenAI") as openai_client,
        ):
            runpy.run_module("harness.agent", run_name="test_agent")
        return token_provider, get_provider, openai_client

    def test_foundry_uses_ai_scope_and_v1_without_api_version(self):
        provider, get_provider, openai_client = self.load_agent({
            "AZURE_OPENAI_ENDPOINT":
                " https://example.services.ai.azure.com/openai/v1/ ",
            "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
        })
        self.assertEqual(
            get_provider.call_args.args[1], "https://ai.azure.com/.default"
        )
        openai_client.assert_called_once_with(
            base_url="https://example.services.ai.azure.com/openai/v1",
            api_key=provider,
        )

    def test_foundry_ignores_legacy_api_version(self):
        _, _, openai_client = self.load_agent({
            "AZURE_OPENAI_ENDPOINT":
                "https://example.services.ai.azure.com/openai/v1",
            "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
            "AZURE_OPENAI_API_VERSION": "2024-10-21",
        })
        self.assertNotIn("api_version", openai_client.call_args.kwargs)

    def test_full_project_v1_endpoint_is_used_unchanged(self):
        endpoint = "https://example.services.ai.azure.com/api/projects/demo/openai/v1"
        provider, get_provider, openai_client = self.load_agent({
            "AZURE_OPENAI_ENDPOINT": endpoint,
            "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
        })
        self.assertEqual(
            get_provider.call_args.args[1],
            "https://ai.azure.com/.default",
        )
        openai_client.assert_called_once_with(
            base_url=endpoint,
            api_key=provider,
        )

    def test_common_required_settings_are_validated(self):
        for missing in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
            with self.subTest(missing=missing):
                settings = {
                    "AZURE_OPENAI_ENDPOINT":
                        "https://example.services.ai.azure.com/openai/v1",
                    "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
                }
                settings[missing] = " "
                with self.assertRaisesRegex(ValueError, missing):
                    self.load_agent(settings)


if __name__ == "__main__":
    unittest.main()
