import json
import os
import runpy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from harness.tools import registry


class AgentClientTests(unittest.TestCase):
    def load_agent(self, settings):
        provider = Mock(return_value="test-token")
        with (
            patch.dict(os.environ, settings, clear=True),
            patch("dotenv.load_dotenv"),
            patch("azure.identity.DefaultAzureCredential") as credential,
            patch(
                "azure.identity.get_bearer_token_provider", return_value=provider
            ) as get_provider,
            patch("openai.OpenAI") as openai_client,
        ):
            agent = runpy.run_module("harness.agent", run_name="test_agent")
        return provider, credential, get_provider, openai_client, agent

    def azure_settings(self):
        return {
            "AZURE_OPENAI_ENDPOINT":
                " https://example.services.ai.azure.com/openai/v1/ ",
            "AZURE_OPENAI_DEPLOYMENT": " test-deployment ",
        }

    def test_foundry_uses_default_credential_and_v1_endpoint(self):
        provider, credential, get_provider, client, agent = self.load_agent(
            self.azure_settings()
        )
        credential.assert_called_once_with()
        get_provider.assert_called_once_with(
            credential.return_value, "https://ai.azure.com/.default"
        )
        client.assert_called_once_with(
            base_url="https://example.services.ai.azure.com/openai/v1",
            api_key=provider,
        )
        self.assertEqual(agent["MODEL"], "test-deployment")
        self.assertEqual(agent["EXTRA_BODY"], {})

    def test_foundry_takes_precedence_over_keys_and_ignores_api_version(self):
        settings = self.azure_settings()
        settings.update({
            "OPENAI_API_KEY": "unused-test-key",
            "KIMI_API_KEY": "unused-test-key",
            "AZURE_OPENAI_API_VERSION": "2024-10-21",
        })
        provider, _, _, client, _ = self.load_agent(settings)
        self.assertIs(client.call_args.kwargs["api_key"], provider)
        self.assertNotIn("api_version", client.call_args.kwargs)

    def test_partial_or_blank_azure_settings_fail_instead_of_falling_back(self):
        for missing in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
            for value in (None, "", " "):
                with self.subTest(missing=missing, value=value):
                    settings = self.azure_settings()
                    settings["KIMI_API_KEY"] = "unused-test-key"
                    if value is None:
                        del settings[missing]
                    else:
                        settings[missing] = value
                    with self.assertRaisesRegex(ValueError, missing):
                        self.load_agent(settings)

    def test_original_openai_backend_is_preserved(self):
        _, credential, get_provider, client, agent = self.load_agent({
            "OPENAI_API_KEY": "test-key",
        })
        client.assert_called_once_with()
        credential.assert_not_called()
        get_provider.assert_not_called()
        self.assertEqual(agent["MODEL"], "gpt-4o-mini")
        self.assertEqual(agent["EXTRA_BODY"], {})

    def test_original_kimi_backend_is_preserved(self):
        _, credential, get_provider, client, agent = self.load_agent({
            "KIMI_API_KEY": "test-key",
            "KIMI_BASE_URL": "https://api.moonshot.ai/v1",
        })
        client.assert_called_once_with(
            api_key="test-key", base_url="https://api.moonshot.ai/v1"
        )
        credential.assert_not_called()
        get_provider.assert_not_called()
        self.assertEqual(agent["MODEL"], "kimi-k2.6")
        self.assertEqual(agent["EXTRA_BODY"], {"thinking": {"type": "disabled"}})

    def test_memory_and_tool_followup_use_foundry_deployment(self):
        for tool_name, arguments in (
            ("bash", '{"command": "echo hello"}'),
            ("git_status", "{}"),
            ("read", '{"path": "example.txt"}'),
        ):
            with self.subTest(tool=tool_name):
                _, _, _, client, agent = self.load_agent(self.azure_settings())
                tool_call = SimpleNamespace(
                    id="call_1",
                    function=SimpleNamespace(name=tool_name, arguments=arguments),
                )
                tool_message = SimpleNamespace(content=None, tool_calls=[tool_call])
                final_message = SimpleNamespace(content="Done.", tool_calls=[])
                create = client.return_value.chat.completions.create
                create.side_effect = [
                    SimpleNamespace(choices=[SimpleNamespace(message=tool_message)]),
                    SimpleNamespace(choices=[SimpleNamespace(message=final_message)]),
                ]
                with (
                    patch("builtins.input", side_effect=["", "Do the task", "quit"]),
                    patch("builtins.print"),
                    patch.dict(agent["run"].__globals__, {
                        "load_agents_md": Mock(return_value="Existing project memory."),
                    }),
                    patch.object(registry, "dispatch", return_value="result") as dispatch,
                ):
                    agent["run"]()
                dispatch.assert_called_once_with(tool_name, json.loads(arguments))
                self.assertEqual(create.call_count, 2)
                for call in create.call_args_list:
                    self.assertEqual(call.kwargs["model"], "test-deployment")
                    tool_names = {
                        schema["function"]["name"] for schema in call.kwargs["tools"]
                    }
                    self.assertTrue({
                        "bash", "git_status", "git_diff", "git_log", "git_commit",
                        "git_checkout", "git_branch", "read", "write", "list",
                        "mkdir", "delete",
                    }.issubset(tool_names))
                    self.assertEqual(call.kwargs["messages"][:2], [
                        {"role": "system", "content": agent["SYSTEM_PROMPT"]},
                        {"role": "system", "content": "Existing project memory."},
                    ])
                self.assertIn(
                    {"role": "tool", "tool_call_id": "call_1", "content": "result"},
                    create.call_args.kwargs["messages"],
                )

    def test_plain_reply_and_exit_do_not_dispatch_tools(self):
        _, _, _, client, agent = self.load_agent(self.azure_settings())
        create = client.return_value.chat.completions.create
        create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content="Hello.", tool_calls=[]))
        ])
        with (
            patch("builtins.input", side_effect=["", "Hello", "exit"]),
            patch("builtins.print") as output,
            patch.dict(agent["run"].__globals__, {
                "load_agents_md": Mock(return_value=""),
            }),
            patch.object(registry, "dispatch") as dispatch,
        ):
            agent["run"]()
        create.assert_called_once()
        dispatch.assert_not_called()
        output.assert_any_call("\nagent > Hello.\n")
        output.assert_any_call("Goodbye.")


if __name__ == "__main__":
    unittest.main()
