import unittest
from types import GeneratorType
from unittest.mock import Mock

from src.handlers.chat import ChatHandler


class _DummyRotator:
    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.api_keys = ["dummy-key"]

    def get_next_key(self) -> str:
        return self.api_keys[0]

    def mark_key_failure(
        self, key: str, is_rate_limit: bool = False, retry_after=None
    ) -> None:
        return None

    def _hash_key(self, key: str) -> str:
        return "dummyhash"


class _DummyApiConfig:
    def __init__(self) -> None:
        self.antigravity_rotator = _DummyRotator("Antigravity")
        self.cli_proxy_api_rotator = _DummyRotator("CLIProxyAPI")
        self.cli_proxy_api_plus_rotator = _DummyRotator("CLIProxyAPIPlus")
        self.ccs_rotator = _DummyRotator("CCS")
        self.cli_proxy_api_gpt_rotator = _DummyRotator("CLIProxyAPI_GPT")
        self.opencode_rotator = _DummyRotator("OpenCode")


class ChatHandlerLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = ChatHandler(_DummyApiConfig())

    def test_standard_provider_payload_includes_max_tokens(self) -> None:
        client = Mock()
        client.post_request.return_value = {"choices": []}
        self.handler.opencode_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "opencode:glm-5.2",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
                "max_tokens": 2048,
            }
        )

        self.assertEqual(result, {"choices": []})
        payload = client.post_request.call_args.kwargs["payload"]
        self.assertEqual(payload["max_tokens"], 2048)

    def test_cli_proxy_api_plus_routes_to_plus_client(self) -> None:
        client = Mock()
        client.post_request.return_value = {"choices": []}
        self.handler.cli_proxy_api_plus_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "cli-proxy-api-plus:gpt-5.5-high",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            }
        )

        self.assertEqual(result, {"choices": []})
        self.assertEqual(
            client.post_request.call_args.kwargs["url"],
            "http://cli-proxy-api-plus:8317/v1/chat/completions",
        )
        payload = client.post_request.call_args.kwargs["payload"]
        self.assertEqual(payload["model"], "gpt-5.5-high")

    def test_ccs_provider_uses_ask_mode_without_payload_tools(self) -> None:
        client = Mock()
        client.post_request.return_value = {"choices": []}
        self.handler.ccs_client = client

        self.handler.handle_chat_request(
            {
                "model": "ccs:composer-2.5",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "Bash",
                            "description": "Run a shell command",
                            "parameters": {
                                "type": "object",
                                "properties": {"command": {"type": "string"}},
                                "required": ["command"],
                            },
                        },
                    }
                ],
                "tool_choice": "auto",
            }
        )

        payload = client.post_request.call_args.kwargs["payload"]
        headers = client.post_request.call_args.kwargs["headers"]
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)
        self.assertEqual(headers["X-Cursor-Mode"], "agent")
        self.assertIn(
            "Claude Code tool bridge instructions",
            payload["messages"][0]["content"],
        )

    def test_request_over_eighty_percent_of_context_uses_compaction_model(self) -> None:
        self.handler._estimate_request_tokens = Mock(return_value=1640001)

        result = self.handler.handle_chat_request(
            {
                "model": "opencode:kimi-k2.6",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            }
        )

        self.assertIn("사용자가 직접", result["choices"][0]["message"]["content"])
        self.assertEqual(result["model"], "opencode:kimi-k2.6")

    def test_request_under_threshold_does_not_use_compaction_model(self) -> None:
        normal_client = Mock()
        normal_client.post_request.return_value = {"choices": []}
        self.handler.opencode_client = normal_client
        self.handler._estimate_request_tokens = Mock(return_value=1000)

        self.handler.handle_chat_request(
            {
                "model": "opencode:kimi-k2.6",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            }
        )

        self.assertTrue(normal_client.post_request.called)

    def test_streaming_request_over_threshold_returns_compaction_notice_stream(
        self,
    ) -> None:
        self.handler._estimate_request_tokens = Mock(return_value=1640001)

        result = self.handler.handle_chat_request(
            {
                "model": "opencode:kimi-k2.6",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            }
        )

        self.assertIsInstance(result, GeneratorType)
        chunks = list(result)
        self.assertIn("사용자가 직접", chunks[0])
        self.assertEqual(chunks[-1], "data: [DONE]\n\n")

    def test_removed_antigravity_legacy_model_is_rejected(self) -> None:
        client = Mock()
        client.post_request.return_value = {"choices": []}
        self.handler.antigravity_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "antigravity:claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            }
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("no longer supported", result.message)
        self.assertFalse(client.post_request.called)

    def test_antigravity_supported_model_is_left_unchanged(self) -> None:
        client = Mock()
        client.post_request.return_value = {"choices": []}
        self.handler.antigravity_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "antigravity:gcli-gemini-3-pro-preview",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            }
        )

        self.assertEqual(result, {"choices": []})
        payload = client.post_request.call_args.kwargs["payload"]
        self.assertEqual(payload["model"], "gcli-gemini-3-pro-preview")


if __name__ == "__main__":
    unittest.main()