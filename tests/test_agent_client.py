import os
import runpy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class AgentClientTests(unittest.TestCase):
    def load_agent(self, settings):
        token_provider = Mock(return_value="test-token")
        with (
            patch.dict(os.environ, settings, clear=True),
            patch("dotenv.load_dotenv"),
            patch("azure.identity.DefaultAzureCredential") as credential,
            patch(
                "azure.identity.get_bearer_token_provider",
                return_value=token_provider,
            ) as get_provider,
            patch("openai.OpenAI") as openai_client,
        ):
            agent = runpy.run_module("harness.agent", run_name="test_agent")
        return token_provider, credential, get_provider, openai_client, agent

    def test_foundry_uses_default_credential_and_v1_without_api_version(self):
        provider, credential, get_provider, openai_client, _ = self.load_agent({
            "AZURE_OPENAI_ENDPOINT":
                " https://example.services.ai.azure.com/openai/v1/ ",
            "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
        })
        credential.assert_called_once_with()
        get_provider.assert_called_once_with(
            credential.return_value, "https://ai.azure.com/.default"
        )
        openai_client.assert_called_once_with(
            base_url="https://example.services.ai.azure.com/openai/v1",
            api_key=provider,
        )

    def test_foundry_ignores_legacy_api_version_and_keys(self):
        provider, _, _, openai_client, _ = self.load_agent({
            "AZURE_OPENAI_ENDPOINT":
                "https://example.services.ai.azure.com/openai/v1",
            "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
            "AZURE_OPENAI_API_VERSION": "2024-10-21",
            "OPENAI_API_KEY": "unused-test-key",
            "KIMI_API_KEY": "unused-test-key",
        })
        self.assertNotIn("api_version", openai_client.call_args.kwargs)
        self.assertIs(openai_client.call_args.kwargs["api_key"], provider)

    def test_full_project_v1_endpoint_is_used_unchanged(self):
        endpoint = "https://example.services.ai.azure.com/api/projects/demo/openai/v1"
        provider, _, _, openai_client, _ = self.load_agent({
            "AZURE_OPENAI_ENDPOINT": endpoint,
            "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
        })
        openai_client.assert_called_once_with(
            base_url=endpoint,
            api_key=provider,
        )

    def test_common_required_settings_are_validated(self):
        for missing in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
            for value in (None, "", " "):
                with self.subTest(missing=missing, value=value):
                    settings = {
                        "AZURE_OPENAI_ENDPOINT":
                            "https://example.services.ai.azure.com/openai/v1",
                        "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
                    }
                    if value is None:
                        del settings[missing]
                    else:
                        settings[missing] = value
                    with self.assertRaisesRegex(ValueError, missing):
                        self.load_agent(settings)

    def test_memory_and_git_tool_followup_use_foundry_deployment(self):
        _, _, _, openai_client, agent = self.load_agent({
            "AZURE_OPENAI_ENDPOINT":
                "https://example.services.ai.azure.com/openai/v1",
            "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
        })
        tool_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name="git_status", arguments="{}"),
        )
        tool_message = SimpleNamespace(content=None, tool_calls=[tool_call])
        final_message = SimpleNamespace(content="Clean workspace.", tool_calls=[])
        create = openai_client.return_value.chat.completions.create
        create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=tool_message)]),
            SimpleNamespace(choices=[SimpleNamespace(message=final_message)]),
        ]
        with (
            patch("builtins.input", side_effect=["", "Check git status", "quit"]),
            patch("builtins.print"),
            patch.dict(agent["run"].__globals__, {
                "load_agents_md": Mock(return_value="Existing project memory."),
            }),
            patch.object(agent["registry"], "dispatch", return_value="clean") as dispatch,
        ):
            agent["run"]()
        dispatch.assert_called_once_with("git_status", {})
        self.assertEqual(create.call_count, 2)
        for call in create.call_args_list:
            self.assertEqual(call.kwargs["model"], "test-deployment")
            self.assertNotIn("extra_body", call.kwargs)
            tool_names = {
                schema["function"]["name"] for schema in call.kwargs["tools"]
            }
            self.assertIn("git_status", tool_names)
            self.assertIn("git_commit", tool_names)
            self.assertIn("read", tool_names)
            self.assertIn("write", tool_names)
            self.assertEqual(call.kwargs["messages"][:2], [
                {"role": "system", "content": agent["SYSTEM_PROMPT"]},
                {"role": "system", "content": "Existing project memory."},
            ])
        messages = create.call_args.kwargs["messages"]
        self.assertIn(
            {"role": "tool", "tool_call_id": "call_1", "content": "clean"},
            messages,
        )


if __name__ == "__main__":
    unittest.main()
