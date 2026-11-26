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
            patch("azure.identity.get_bearer_token_provider", return_value=provider) as tokens,
            patch("openai.OpenAI") as client,
        ):
            agent = runpy.run_module("harness.agent", run_name="test_agent")
        return provider, credential, tokens, client, agent

    def settings(self):
        return {
            "AZURE_OPENAI_ENDPOINT": " https://example.services.ai.azure.com/openai/v1/ ",
            "AZURE_OPENAI_DEPLOYMENT": " test-deployment ",
        }

    def test_foundry_authentication_and_precedence(self):
        settings = self.settings()
        settings.update(OPENAI_API_KEY="unused", KIMI_API_KEY="unused")
        provider, credential, tokens, client, agent = self.load_agent(settings)
        credential.assert_called_once_with()
        tokens.assert_called_once_with(
            credential.return_value, "https://ai.azure.com/.default"
        )
        client.assert_called_once_with(
            base_url="https://example.services.ai.azure.com/openai/v1", api_key=provider
        )
        self.assertEqual(agent["MODEL"], "test-deployment")

    def test_incomplete_settings_fail_without_fallback(self):
        for missing in self.settings():
            for value in (None, "", " "):
                with self.subTest(missing=missing, value=value):
                    settings = self.settings()
                    settings["KIMI_API_KEY"] = "unused"
                    if value is None:
                        del settings[missing]
                    else:
                        settings[missing] = value
                    with self.assertRaisesRegex(ValueError, missing):
                        self.load_agent(settings)

    def test_original_backends_preserve_configuration(self):
        for settings, kwargs in (
            ({"OPENAI_API_KEY": "test"}, {}),
            (
                {"KIMI_API_KEY": "test", "KIMI_BASE_URL": "https://api.moonshot.ai/v1"},
                {"api_key": "test", "base_url": "https://api.moonshot.ai/v1"},
            ),
        ):
            with self.subTest(settings=settings):
                _, credential, tokens, client, agent = self.load_agent(settings)
                client.assert_called_once_with(**kwargs)
                credential.assert_not_called()
                tokens.assert_not_called()
                self.assertEqual(agent["MODEL"], MODEL)

    def response(self, content=None, tool_call=False):
        calls = [SimpleNamespace(
            id="search-call",
            function=SimpleNamespace(name="web_search", arguments='{"query": "test"}'),
        )] if tool_call else []
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=calls)
        )])

    def test_web_search_dispatch_and_memory_consolidation(self):
        _, _, _, client, agent = self.load_agent(self.settings())
        create = client.return_value.chat.completions.create
        create.side_effect = [
            self.response(tool_call=True),
            self.response(content="Done."),
            self.response(content=AGENTS_MD_TEMPLATE),
        ]
        sandbox = Mock()
        with (
            patch("builtins.input", side_effect=["", "Search", "quit"]),
            patch("builtins.print"),
            patch.dict(agent["run"].__globals__, {
                "Sandbox": Mock(return_value=sandbox),
                "set_sandbox": Mock(),
                "load_agents_md": Mock(return_value=AGENTS_MD_TEMPLATE),
                "save_agents_md": Mock(),
            }),
            patch.object(registry, "dispatch", return_value="search results") as dispatch,
        ):
            save = agent["run"].__globals__["save_agents_md"]
            agent["run"]()
            save.assert_called_once_with(AGENTS_MD_TEMPLATE)
        sandbox.start.assert_called_once_with()
        sandbox.stop.assert_called_once_with()
        dispatch.assert_called_once_with("web_search", {"query": "test"})
        self.assertEqual(create.call_count, 3)
        for request in create.call_args_list:
            self.assertEqual(request.kwargs["model"], "test-deployment")
        self.assertEqual(create.call_args_list[0].kwargs["tools"], registry.get_schemas())
        self.assertIn(
            {"role": "tool", "tool_call_id": "search-call", "content": "search results"},
            create.call_args.kwargs["messages"],
        )
        self.assertNotIn("tools", create.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
