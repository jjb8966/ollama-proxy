import json
import unittest
from types import GeneratorType
from unittest.mock import Mock

from src.handlers.chat import ChatHandler
from src.utils.opencode_anthropic import (
    anthropic_response_to_openai,
    build_anthropic_payload,
    uses_opencode_anthropic_messages,
)
from tests.test_chat_handler_limits import _DummyApiConfig


class OpenCodeAnthropicUtilityTests(unittest.TestCase):
    def test_qwen3_7_max_uses_anthropic_messages_endpoint(self) -> None:
        self.assertTrue(uses_opencode_anthropic_messages("qwen3.7-max"))
        self.assertFalse(uses_opencode_anthropic_messages("qwen3.7-plus"))

    def test_build_anthropic_payload_from_openai_messages(self) -> None:
        payload = build_anthropic_payload(
            model="qwen3.7-max",
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hello"},
            ],
            stream=False,
            max_tokens=20,
        )

        self.assertEqual(payload["model"], "qwen3.7-max")
        self.assertEqual(payload["system"], "You are helpful.")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])

    def test_anthropic_response_to_openai(self) -> None:
        converted = anthropic_response_to_openai(
            {
                "id": "msg_test",
                "model": "qwen3.7-max",
                "content": [
                    {"type": "thinking", "thinking": "reason"},
                    {"type": "text", "text": "Hi"},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            "opencode:qwen3.7-max",
        )

        message = converted["choices"][0]["message"]
        self.assertEqual(message["content"], "Hi")
        self.assertEqual(message["reasoning_content"], "reason")
        self.assertEqual(converted["model"], "opencode:qwen3.7-max")
        self.assertEqual(converted["usage"]["total_tokens"], 15)


class ChatHandlerOpenCodeAnthropicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = ChatHandler(_DummyApiConfig())

    def test_opencode_qwen3_7_max_routes_to_messages_endpoint(self) -> None:
        client = Mock()
        client._get_api_key.return_value = "dummy-key"
        client.post_request.return_value = {
            "id": "msg_test",
            "model": "qwen3.7-max",
            "content": [{"type": "text", "text": "Hi"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        self.handler.opencode_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "opencode:qwen3.7-max",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            }
        )

        self.assertEqual(result["choices"][0]["message"]["content"], "Hi")
        call_kwargs = client.post_request.call_args.kwargs
        self.assertEqual(
            call_kwargs["url"],
            "https://opencode.ai/zen/go/v1/messages",
        )
        self.assertEqual(call_kwargs["headers"]["x-api-key"], "dummy-key")
        self.assertEqual(call_kwargs["payload"]["model"], "qwen3.7-max")

    def test_opencode_qwen3_7_plus_still_uses_chat_completions(self) -> None:
        client = Mock()
        client.post_request.return_value = {"choices": []}
        self.handler.opencode_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "opencode:qwen3.7-plus",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            }
        )

        self.assertEqual(result, {"choices": []})
        self.assertEqual(
            client.post_request.call_args.kwargs["url"],
            "https://opencode.ai/zen/go/v1/chat/completions",
        )
        payload = client.post_request.call_args.kwargs["payload"]
        self.assertEqual(payload["model"], "qwen3.7-plus")

    def test_opencode_qwen3_7_max_streaming_returns_generator(self) -> None:
        client = Mock()
        client._get_api_key.return_value = "dummy-key"

        class _FakeResponse:
            def iter_lines(self, decode_unicode=True):
                yield 'event: content_block_delta'
                yield 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}'
                yield 'event: message_delta'
                yield 'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}'

            def close(self):
                return None

        client.post_request.return_value = _FakeResponse()
        self.handler.opencode_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "opencode:qwen3.7-max",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            }
        )

        self.assertIsInstance(result, GeneratorType)
        chunks = list(result)
        self.assertTrue(any("Hi" in chunk for chunk in chunks))
        self.assertEqual(chunks[-1], "data: [DONE]\n\n")


if __name__ == "__main__":
    unittest.main()
