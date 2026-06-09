import json
import unittest
from types import GeneratorType
from unittest.mock import Mock

from src.handlers.chat import ChatHandler
from src.utils.opencode_anthropic import (
    AnthropicMessagePassthrough,
    AnthropicSsePassthrough,
    anthropic_response_to_openai,
    build_anthropic_payload,
    stream_anthropic_sse_to_openai,
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

    def test_build_anthropic_payload_merges_parallel_tool_results(self) -> None:
        payload = build_anthropic_payload(
            model="qwen3.7-max",
            messages=[
                {"role": "user", "content": "Search qwen and glm"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "toolu_a1",
                            "type": "function",
                            "function": {
                                "name": "WebSearch",
                                "arguments": '{"query": "qwen"}',
                            },
                        },
                        {
                            "id": "toolu_a2",
                            "type": "function",
                            "function": {
                                "name": "WebSearch",
                                "arguments": '{"query": "glm"}',
                            },
                        },
                    ],
                },
                {"role": "tool", "tool_call_id": "toolu_a1", "content": "qwen result"},
                {"role": "tool", "tool_call_id": "toolu_a2", "content": "glm result"},
            ],
            stream=False,
            max_tokens=100,
        )

        user_messages = [msg for msg in payload["messages"] if msg["role"] == "user"]
        self.assertEqual(len(user_messages), 2)
        tool_result_message = user_messages[-1]
        content = tool_result_message["content"]
        self.assertIsInstance(content, list)
        tool_results = [block for block in content if block.get("type") == "tool_result"]
        self.assertEqual(len(tool_results), 2)
        self.assertEqual(tool_results[0]["tool_use_id"], "toolu_a1")
        self.assertEqual(tool_results[1]["tool_use_id"], "toolu_a2")

    def test_anthropic_response_to_openai(self) -> None:
        converted = anthropic_response_to_openai(
            {
                "id": "msg_test",
                "model": "qwen3.7-max",
                "content": [
                    {"type": "thinking", "thinking": "reason"},
                    {"type": "text", "text": "안녕하세요"},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            "opencode:qwen3.7-max",
        )

        message = converted["choices"][0]["message"]
        self.assertEqual(message["content"], "안녕하세요")
        self.assertEqual(message["reasoning_content"], "reason")
        self.assertEqual(converted["model"], "opencode:qwen3.7-max")
        self.assertEqual(converted["usage"]["total_tokens"], 15)

    def test_stream_anthropic_sse_to_openai_preserves_korean(self) -> None:
        lines = [
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"모델"}}',
        ]
        chunks = list(stream_anthropic_sse_to_openai(lines, "opencode:qwen3.7-max"))
        self.assertTrue(any("모델" in chunk for chunk in chunks))

    def test_stream_anthropic_sse_to_openai_emits_tool_calls(self) -> None:
        lines = [
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_test","name":"WebSearch","input":{}}}',
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"query\\":\\"test\\"}"}}',
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"}}',
        ]
        chunks = list(stream_anthropic_sse_to_openai(lines, "opencode:qwen3.7-max"))
        combined = "".join(chunks)
        self.assertIn("WebSearch", combined)
        self.assertIn("tool_calls", combined)
        self.assertIn("toolu_test", combined)
        self.assertIn("query", combined)


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

    def test_opencode_qwen3_7_max_anthropic_passthrough_stream(self) -> None:
        client = Mock()
        client._get_api_key.return_value = "dummy-key"

        class _FakeResponse:
            def iter_lines(self, decode_unicode=True):
                yield 'event: content_block_start'
                yield 'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"toolu_test","name":"WebSearch","input":{}},"index":1}'

            def close(self):
                return None

        client.post_request.return_value = _FakeResponse()
        self.handler.opencode_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "opencode:qwen3.7-max",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
                "_anthropic_passthrough": True,
            }
        )

        self.assertIsInstance(result, AnthropicSsePassthrough)
        chunks = list(result)
        self.assertTrue(any("tool_use" in chunk for chunk in chunks))
        self.assertTrue(any("WebSearch" in chunk for chunk in chunks))

    def test_opencode_qwen3_7_max_anthropic_passthrough_non_stream(self) -> None:
        client = Mock()
        client._get_api_key.return_value = "dummy-key"
        client.post_request.return_value = type(
            "Resp",
            (),
            {
                "content": json.dumps(
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "toolu_test",
                                "name": "WebSearch",
                                "input": {"query": "test"},
                            }
                        ],
                        "stop_reason": "tool_use",
                    }
                ).encode("utf-8")
            },
        )()
        self.handler.opencode_client = client

        result = self.handler.handle_chat_request(
            {
                "model": "opencode:qwen3.7-max",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
                "_anthropic_passthrough": True,
            }
        )

        self.assertIsInstance(result, AnthropicMessagePassthrough)
        self.assertEqual(result.data["stop_reason"], "tool_use")
        self.assertEqual(result.data["content"][0]["name"], "WebSearch")


if __name__ == "__main__":
    unittest.main()
