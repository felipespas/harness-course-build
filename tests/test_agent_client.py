import os
import runpy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from harness.config import MODEL
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

    def test_foundry_takes_precedence_over_api_keys(self):
        settings = self.azure_settings()
        settings.update({
            "OPENAI_API_KEY": "unused-test-key",
            "KIMI_API_KEY": "unused-test-key",
        })
        provider, _, _, client, _ = self.load_agent(settings)
        self.assertIs(client.call_args.kwargs["api_key"], provider)

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

    def test_original_backends_preserve_configured_model(self):
        for settings, kwargs, extra_body in (
            ({"OPENAI_API_KEY": "test-key"}, {}, {}),
            (
                {
                    "KIMI_API_KEY": "test-key",
                    "KIMI_BASE_URL": "https://api.moonshot.ai/v1",
                },
                {"api_key": "test-key", "base_url": "https://api.moonshot.ai/v1"},
                {"thinking": {"type": "disabled"}},
            ),
        ):
            with self.subTest(settings=settings):
                _, credential, get_provider, client, agent = self.load_agent(settings)
                client.assert_called_once_with(**kwargs)
                credential.assert_not_called()
                get_provider.assert_not_called()
                self.assertEqual(agent["MODEL"], MODEL)
                self.assertEqual(agent["EXTRA_BODY"], extra_body)

    def run_conversation(self, agent):
        sandbox = Mock()
        set_sandbox = Mock()
        with (
            patch("builtins.input", side_effect=["", "Do the task", "quit"]),
            patch("builtins.print") as output,
            patch.dict(agent["run"].__globals__, {
                "load_agents_md": Mock(return_value="Existing project memory."),
                "Sandbox": Mock(return_value=sandbox),
                "set_sandbox": set_sandbox,
            }),
            patch.object(registry, "dispatch", return_value="result") as dispatch,
        ):
            try:
                agent["run"]()
            finally:
                sandbox.start.assert_called_once_with()
                set_sandbox.assert_called_once_with(sandbox)
                sandbox.stop.assert_called_once_with()
        return output, dispatch

    def response(self, content=None, call_id=None):
        calls = []
        if call_id:
            calls.append(SimpleNamespace(
                id=call_id,
                function=SimpleNamespace(name="git_status", arguments="{}"),
            ))
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))
        ])

    def test_foundry_preserves_multiple_react_rounds_and_memory(self):
        _, _, _, client, agent = self.load_agent(self.azure_settings())
        create = client.return_value.chat.completions.create
        create.side_effect = [
            self.response(call_id="call_1"),
            self.response(call_id="call_2"),
            self.response(content="Done."),
        ]
        output, dispatch = self.run_conversation(agent)
        self.assertEqual(dispatch.call_args_list, [
            call("git_status", {}), call("git_status", {}),
        ])
        self.assertEqual(create.call_count, 3)
        for request in create.call_args_list:
            self.assertEqual(request.kwargs["model"], "test-deployment")
            self.assertEqual(request.kwargs["tools"], registry.get_schemas())
            self.assertEqual(request.kwargs["messages"][:2], [
                {"role": "system", "content": agent["SYSTEM_PROMPT"]},
                {"role": "system", "content": "Existing project memory."},
            ])
        for call_id in ("call_1", "call_2"):
            self.assertIn(
                {"role": "tool", "tool_call_id": call_id, "content": "result"},
                create.call_args.kwargs["messages"],
            )
        output.assert_any_call("\nagent > Done.\n")

    def test_foundry_budget_summary_uses_same_deployment_and_disables_tools(self):
        _, _, _, client, agent = self.load_agent(self.azure_settings())
        create = client.return_value.chat.completions.create
        create.side_effect = [
            self.response(call_id=f"call_{index}")
            for index in range(agent["STEP_BUDGET"] + 1)
        ] + [self.response(content="Budget summary.")]
        output, dispatch = self.run_conversation(agent)
        self.assertEqual(dispatch.call_count, agent["STEP_BUDGET"])
        self.assertEqual(create.call_count, agent["STEP_BUDGET"] + 2)
        self.assertEqual(create.call_args.kwargs["model"], "test-deployment")
        self.assertEqual(create.call_args.kwargs["tool_choice"], "none")
        self.assertIn(
            {"role": "system", "content": agent["BUDGET_HIT_MESSAGE"]},
            create.call_args.kwargs["messages"],
        )
        output.assert_any_call("\nagent > Budget summary.\n")

    def test_foundry_error_preserves_sandbox_teardown(self):
        _, _, _, client, agent = self.load_agent(self.azure_settings())
        client.return_value.chat.completions.create.side_effect = RuntimeError(
            "Model request failed"
        )
        with self.assertRaisesRegex(RuntimeError, "Model request failed"):
            self.run_conversation(agent)


if __name__ == "__main__":
    unittest.main()
