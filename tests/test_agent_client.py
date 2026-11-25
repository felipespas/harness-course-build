import os
import runpy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from harness.config import MODEL
from harness.memory.agents_md import AGENTS_MD_TEMPLATE
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
            patch("openai.OpenAI") as client,
        ):
            agent = runpy.run_module("harness.agent", run_name="test_agent")
        return provider, credential, get_provider, client, agent

    def azure_settings(self):
        return {
            "AZURE_OPENAI_ENDPOINT":
                " https://example.services.ai.azure.com/openai/v1/ ",
            "AZURE_OPENAI_DEPLOYMENT": " test-deployment ",
        }

    def test_foundry_uses_default_credential_and_takes_precedence(self):
        settings = self.azure_settings()
        settings.update(OPENAI_API_KEY="unused", KIMI_API_KEY="unused")
        provider, credential, get_provider, client, agent = self.load_agent(settings)
        credential.assert_called_once_with()
        get_provider.assert_called_once_with(
            credential.return_value, "https://ai.azure.com/.default"
        )
        client.assert_called_once_with(
            base_url="https://example.services.ai.azure.com/openai/v1",
            api_key=provider,
        )
        self.assertEqual(agent["MODEL"], "test-deployment")

    def test_partial_or_blank_settings_fail_without_fallback(self):
        for missing in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
            for value in (None, "", " "):
                with self.subTest(missing=missing, value=value):
                    settings = self.azure_settings()
                    settings["KIMI_API_KEY"] = "unused"
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
                {"KIMI_API_KEY": "test-key", "KIMI_BASE_URL": "https://api.moonshot.ai/v1"},
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

    def response(self, content=None, call_id=None):
        calls = [] if call_id is None else [SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(name="git_status", arguments="{}"),
        )]
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=calls)
        )])

    def run_conversation(self, agent):
        sandbox = Mock()
        wire = Mock()
        save = Mock()
        with (
            patch("builtins.input", side_effect=["", "Do the task", "quit"]),
            patch("builtins.print"),
            patch.dict(agent["run"].__globals__, {
                "load_agents_md": Mock(return_value=AGENTS_MD_TEMPLATE),
                "save_agents_md": save,
                "Sandbox": Mock(return_value=sandbox),
                "set_sandbox": wire,
            }),
            patch.object(registry, "dispatch", return_value="result") as dispatch,
        ):
            try:
                agent["run"]()
            finally:
                sandbox.start.assert_called_once_with()
                wire.assert_called_once_with(sandbox)
                sandbox.stop.assert_called_once_with()
        return dispatch, save

    def test_react_rounds_and_exit_consolidation_use_foundry(self):
        _, _, _, client, agent = self.load_agent(self.azure_settings())
        create = client.return_value.chat.completions.create
        create.side_effect = [
            self.response(call_id="call_1"),
            self.response(call_id="call_2"),
            self.response(content="Done."),
            self.response(content=AGENTS_MD_TEMPLATE),
        ]
        dispatch, save = self.run_conversation(agent)
        self.assertEqual(dispatch.call_count, 2)
        self.assertEqual(create.call_count, 4)
        for request in create.call_args_list:
            self.assertEqual(request.kwargs["model"], "test-deployment")
            self.assertEqual(request.kwargs["messages"][:2], [
                {"role": "system", "content": agent["SYSTEM_PROMPT"]},
                {"role": "system", "content": AGENTS_MD_TEMPLATE},
            ])
        for call_id in ("call_1", "call_2"):
            self.assertIn(
                {"role": "tool", "tool_call_id": call_id, "content": "result"},
                create.call_args.kwargs["messages"],
            )
        self.assertNotIn("tools", create.call_args.kwargs)
        self.assertIn(
            agent["SESSION_END_MEMORY_PROMPT"],
            create.call_args.kwargs["messages"][-1]["content"],
        )
        save.assert_called_once_with(AGENTS_MD_TEMPLATE)

    def test_budget_summary_uses_foundry_and_disables_tools(self):
        _, _, _, client, agent = self.load_agent(self.azure_settings())
        create = client.return_value.chat.completions.create
        create.side_effect = [
            self.response(call_id=f"call_{index}")
            for index in range(agent["STEP_BUDGET"] + 1)
        ] + [
            self.response(content="Budget summary."),
            self.response(content=AGENTS_MD_TEMPLATE),
        ]
        dispatch, save = self.run_conversation(agent)
        self.assertEqual(dispatch.call_count, agent["STEP_BUDGET"])
        self.assertEqual(create.call_count, agent["STEP_BUDGET"] + 3)
        summary = create.call_args_list[-2].kwargs
        self.assertEqual(summary["model"], "test-deployment")
        self.assertEqual(summary["tool_choice"], "none")
        self.assertIn(
            {"role": "system", "content": agent["BUDGET_HIT_MESSAGE"]},
            summary["messages"],
        )
        save.assert_called_once_with(AGENTS_MD_TEMPLATE)

    def test_model_error_preserves_sandbox_teardown(self):
        _, _, _, client, agent = self.load_agent(self.azure_settings())
        client.return_value.chat.completions.create.side_effect = RuntimeError(
            "Model request failed"
        )
        with self.assertRaisesRegex(RuntimeError, "Model request failed"):
            self.run_conversation(agent)


if __name__ == "__main__":
    unittest.main()
