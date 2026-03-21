import json
import unittest

from src.handlers.anthropic import AnthropicHandler


class AnthropicHandlerNormalizeMessagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = AnthropicHandler()

    def test_tool_result_follows_assistant_tool_call_without_blank_user_message(
        self,
    ) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "bash",
                        "input": {"command": "pwd"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "output",
                    }
                ],
            },
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(
            normalized,
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "toolu_123",
                            "type": "function",
                            "function": {
                                "name": "bash",
                                "arguments": json.dumps(
                                    {"command": "pwd"}, ensure_ascii=False
                                ),
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "toolu_123", "content": "output"},
            ],
        )

    def test_assistant_text_and_tool_use_stay_in_one_message(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "확인 후 실행하겠습니다."},
                    {
                        "type": "tool_use",
                        "id": "toolu_456",
                        "name": "bash",
                        "input": {"command": "ls"},
                    },
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["role"], "assistant")
        self.assertEqual(normalized[0]["content"], "확인 후 실행하겠습니다.")
        self.assertEqual(normalized[0]["tool_calls"][0]["id"], "toolu_456")

    def test_user_text_after_tool_result_is_preserved_after_tool_message(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_789",
                        "content": [{"type": "text", "text": "command output"}],
                    },
                    {
                        "type": "text",
                        "text": "이 결과를 바탕으로 다음 단계 진행해 주세요.",
                    },
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(
            normalized,
            [
                {
                    "role": "tool",
                    "tool_call_id": "toolu_789",
                    "content": "command output",
                },
                {
                    "role": "user",
                    "content": "이 결과를 바탕으로 다음 단계 진행해 주세요.",
                },
            ],
        )

    def test_text_only_content_blocks_remain_plain_messages(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "안녕하세요."},
                    {"type": "text", "text": "계속 진행해 주세요."},
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(
            normalized, [{"role": "user", "content": "안녕하세요.계속 진행해 주세요."}]
        )

    def test_invalid_dict_response_is_rejected_in_non_streaming_transform(self) -> None:
        with self.assertRaisesRegex(ValueError, "OpenAI-compatible"):
            self.handler.handle_non_streaming_response(
                {
                    "model": "ollama-cloud:kimi-k2.5",
                    "message": {"role": "assistant", "content": "bad"},
                    "done": True,
                },
                "ollama-cloud:kimi-k2.5",
            )

    def test_non_streaming_response_tolerates_null_tool_calls(self) -> None:
        response = self.handler.handle_non_streaming_response(
            {
                "model": "cli-proxy-api-gpt:gpt-5.4",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "정상 응답입니다.",
                            "tool_calls": None,
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                },
            },
            "cli-proxy-api-gpt:gpt-5.4",
        )

        self.assertEqual(
            response["content"], [{"type": "text", "text": "정상 응답입니다."}]
        )
        self.assertEqual(response["stop_reason"], "end_turn")

    def test_normalize_tools_adds_empty_properties_for_object_schema(self) -> None:
        normalized = self.handler._normalize_tools(
            [
                {
                    "name": "mcp__pencil__get_style_guide_tags",
                    "description": "style guide tags",
                    "input_schema": {"type": "object"},
                }
            ]
        )

        self.assertEqual(
            normalized,
            [
                {
                    "type": "function",
                    "function": {
                        "name": "mcp__pencil__get_style_guide_tags",
                        "description": "style guide tags",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

    def test_normalize_tools_uses_default_schema_for_non_dict_input_schema(
        self,
    ) -> None:
        normalized = self.handler._normalize_tools(
            [
                {
                    "name": "tool_without_schema_dict",
                    "input_schema": "invalid",
                }
            ]
        )

        self.assertEqual(
            normalized[0]["function"]["parameters"],
            {"type": "object", "properties": {}},
        )

    def test_normalize_tools_sanitizes_nested_object_schemas(self) -> None:
        normalized = self.handler._normalize_tools(
            [
                {
                    "name": "nested_tool",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "config": {
                                "type": "object",
                                "properties": {
                                    "theme": {"type": "string"},
                                    "options": {"type": "object"},
                                },
                            },
                            "metadata": {"type": "object"},
                        },
                    },
                }
            ]
        )

        parameters = normalized[0]["function"]["parameters"]
        self.assertEqual(
            parameters["properties"]["metadata"], {"type": "object", "properties": {}}
        )
        self.assertEqual(
            parameters["properties"]["config"]["properties"]["options"],
            {"type": "object", "properties": {}},
        )

    def test_sanitize_tool_input_schema_removes_non_standard_keywords(self) -> None:
        schema = {
            "type": "object",
            "title": "MyTool",
            "description": "A tool with extra keys",
            "additionalProperties": False,
            "default": {},
            "$schema": "http://json-schema.org/draft-07/schema#",
            "properties": {
                "name": {
                    "type": "string",
                    "format": "email",
                    "pattern": "^[a-z]+$",
                }
            },
        }

        sanitized = self.handler._sanitize_tool_input_schema(schema)

        self.assertEqual(sanitized["type"], "object")
        self.assertEqual(sanitized["description"], "A tool with extra keys")
        self.assertIn("properties", sanitized)

        self.assertNotIn("title", sanitized)
        self.assertNotIn("additionalProperties", sanitized)
        self.assertNotIn("default", sanitized)
        self.assertNotIn("$schema", sanitized)

        name_prop = sanitized["properties"]["name"]
        self.assertEqual(name_prop["type"], "string")
        self.assertNotIn("format", name_prop)
        self.assertNotIn("pattern", name_prop)

    def test_sanitize_tool_input_schema_preserves_standard_keywords(self) -> None:
        schema = {
            "type": "object",
            "description": "All standard keys",
            "enum": ["a", "b"],
            "properties": {"p": {"type": "string"}},
            "required": ["p"],
            "nullable": True,
            "anyOf": [{"type": "string"}, {"type": "number"}],
            "oneOf": [{"type": "boolean"}],
            "allOf": [{"type": "object"}],
        }

        sanitized = self.handler._sanitize_tool_input_schema(schema)

        for key in [
            "type",
            "description",
            "enum",
            "properties",
            "required",
            "nullable",
            "anyOf",
            "oneOf",
            "allOf",
        ]:
            self.assertIn(key, sanitized)

    def test_sanitize_tool_input_schema_recursive_sanitization(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "list": {
                    "type": "array",
                    "items": {"type": "string", "title": "ItemTitle"},
                },
                "union": {
                    "anyOf": [
                        {"type": "string", "format": "date"},
                        {"type": "number", "default": 0},
                    ]
                },
            },
        }

        sanitized = self.handler._sanitize_tool_input_schema(schema)

        items = sanitized["properties"]["list"]["items"]
        self.assertEqual(items["type"], "string")
        self.assertNotIn("title", items)

        any_of = sanitized["properties"]["union"]["anyOf"]
        self.assertEqual(any_of[0]["type"], "string")
        self.assertNotIn("format", any_of[0])
        self.assertEqual(any_of[1]["type"], "number")
        self.assertNotIn("default", any_of[1])

    def test_normalize_tools_integration_sanitization(self) -> None:
        tools = [
            {
                "name": "my_tool",
                "description": "desc",
                "input_schema": {
                    "type": "object",
                    "title": "ToolTitle",
                    "properties": {"p": {"type": "string", "format": "uri"}},
                },
            }
        ]

        normalized = self.handler._normalize_tools(tools)

        params = normalized[0]["function"]["parameters"]
        self.assertNotIn("title", params)
        self.assertNotIn("format", params["properties"]["p"])
        self.assertEqual(params["properties"]["p"]["type"], "string")


class AnthropicHandlerStreamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = AnthropicHandler()

    @staticmethod
    def _stream(lines):
        for line in lines:
            yield line

    def test_stream_uses_delta_text_when_content_is_missing(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"text":"안녕하세요"},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(
                resp, "ollama-cloud:kimi-k2.5", "req_text"
            )
        )

        joined = "".join(chunks)
        self.assertIn("안녕하세요", joined)
        self.assertIn("event: message_stop", joined)

    def test_stream_uses_message_content_when_delta_content_is_missing(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{},"message":{"content":"반갑습니다."},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(
                resp, "ollama-cloud:kimi-k2.5", "req_msg"
            )
        )

        joined = "".join(chunks)
        self.assertIn("반갑습니다.", joined)
        self.assertIn("event: message_stop", joined)

    def test_stream_uses_reasoning_content_when_standard_text_is_missing(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"reasoning_content":"먼저 변경 사항을 확인했습니다."},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(
                resp, "ollama-cloud:kimi-k2.5", "req_reasoning"
            )
        )

        joined = "".join(chunks)
        self.assertIn("먼저 변경 사항을 확인했습니다.", joined)
        self.assertIn("event: message_stop", joined)

    def test_stream_logs_warning_for_empty_end_turn_response(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        with self.assertLogs("src.handlers.anthropic", level="WARNING") as logs:
            chunks = list(
                self.handler.stream_anthropic_response(
                    resp,
                    "ollama-cloud:kimi-k2.5",
                    "req_empty_end_turn",
                )
            )

        self.assertIn("event: message_stop", "".join(chunks))
        self.assertTrue(any("빈 end_turn 응답" in message for message in logs.output))

    def test_stream_logs_warning_when_done_marker_is_missing(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"text":"중간 응답"},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
            ]
        )

        with self.assertLogs("src.handlers.anthropic", level="WARNING") as logs:
            chunks = list(
                self.handler.stream_anthropic_response(
                    resp,
                    "ollama-cloud:kimi-k2.5",
                    "req_no_done",
                )
            )

        self.assertIn("중간 응답", "".join(chunks))
        self.assertTrue(
            any("[DONE] 없이 스트림 종료" in message for message in logs.output)
        )

    def test_stream_logs_warning_when_generator_is_closed(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"text":"첫 청크"},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        stream = self.handler.stream_anthropic_response(
            resp,
            "ollama-cloud:kimi-k2.5",
            "req_generator_close",
        )
        next(stream)

        with self.assertLogs("src.handlers.anthropic", level="WARNING") as logs:
            stream.close()

        self.assertTrue(any("generator 종료" in message for message in logs.output))

    def test_stream_tolerates_null_tool_calls(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"content":"안녕하세요","tool_calls":null},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{"tool_calls":null},"finish_reason":"stop"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(
                resp,
                "cli-proxy-api-gpt:gpt-5.4",
                "req_null_tool_calls",
            )
        )

        joined = "".join(chunks)
        self.assertIn("안녕하세요", joined)
        self.assertIn("event: message_stop", joined)


if __name__ == "__main__":
    unittest.main()
