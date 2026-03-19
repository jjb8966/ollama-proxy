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

    def mark_key_failure(self, key: str, is_rate_limit: bool = False, retry_after=None) -> None:
        return None

    def _hash_key(self, key: str) -> str:
        return "dummyhash"


class _DummyQwenOAuthManager:
    def get_access_token(self) -> str:
        return "dummy-token"

    def refresh_access_token(self) -> bool:
        return False


class _DummyApiConfig:
    def __init__(self) -> None:
        self.google_rotator = _DummyRotator("Google")
        self.openrouter_rotator = _DummyRotator("OpenRouter")
        self.akash_rotator = _DummyRotator("Akash")
        self.cohere_rotator = _DummyRotator("Cohere")
        self.codestral_rotator = _DummyRotator("Codestral")
        self.qwen_oauth_manager = _DummyQwenOAuthManager()
        self.antigravity_rotator = _DummyRotator("Antigravity")
        self.nvidia_nim_rotator = _DummyRotator("NvidiaNIM")
        self.cli_proxy_api_rotator = _DummyRotator("CLIProxyAPI")
        self.cli_proxy_api_gpt_rotator = _DummyRotator("CLIProxyAPI_GPT")
        self.ollama_cloud_rotator = _DummyRotator("OllamaCloud")


class ChatHandlerLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = ChatHandler(_DummyApiConfig())

    def test_standard_provider_payload_includes_max_tokens(self) -> None:
        client = Mock()
        client.post_request.return_value = {"choices": []}
        self.handler.ollama_cloud_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "ollama-cloud:minimax-m2.5",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
                "max_tokens": 2048,
            }
        )

        self.assertEqual(result, {"choices": []})
        payload = client.post_request.call_args.kwargs["payload"]
        self.assertEqual(payload["max_tokens"], 2048)

    def test_request_over_eighty_percent_of_context_uses_compaction_model(self) -> None:
        self.handler._estimate_request_tokens = Mock(return_value=204801)

        result = self.handler.handle_chat_request(
            {
                "model": "cohere:command-a-03-2025",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            }
        )

        self.assertIn("사용자가 직접", result["choices"][0]["message"]["content"])
        self.assertEqual(result["model"], "cohere:command-a-03-2025")

    def test_request_under_threshold_does_not_use_compaction_model(self) -> None:
        normal_client = Mock()
        normal_client.post_request.return_value = {"choices": []}
        cli_proxy_api_client = Mock()
        self.handler.cohere_client = normal_client
        self.handler.cli_proxy_api_client = cli_proxy_api_client
        self.handler._estimate_request_tokens = Mock(return_value=1000)

        self.handler.handle_chat_request(
            {
                "model": "cohere:command-a-03-2025",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            }
        )

        self.assertTrue(normal_client.post_request.called)
        self.assertFalse(cli_proxy_api_client.post_request.called)

    def test_streaming_request_over_threshold_returns_compaction_notice_stream(self) -> None:
        self.handler._estimate_request_tokens = Mock(return_value=204801)

        result = self.handler.handle_chat_request(
            {
                "model": "cohere:command-a-03-2025",
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

    def test_removed_antigravity_gcli_31_model_is_rejected(self) -> None:
        client = Mock()
        client.post_request.return_value = {"choices": []}
        self.handler.antigravity_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "antigravity:gcli-gemini-3.1-pro-preview",
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
