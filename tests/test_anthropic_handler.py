import json
import unittest

from src.handlers.anthropic import AnthropicHandler


class AnthropicHandlerNormalizeMessagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = AnthropicHandler()

    def test_tool_result_follows_assistant_tool_call_without_blank_user_message(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "bash",
                        "input": {"command": "pwd"}
                    }
                ]
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "output"
                    }
                ]
            }
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
                                "arguments": json.dumps({"command": "pwd"}, ensure_ascii=False)
                            }
                        }
                    ]
                },
                {
                    "role": "tool",
                    "tool_call_id": "toolu_123",
                    "content": "output"
                }
            ]
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
                        "input": {"command": "ls"}
                    }
                ]
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
                        "content": [{"type": "text", "text": "command output"}]
                    },
                    {"type": "text", "text": "이 결과를 바탕으로 다음 단계 진행해 주세요."}
                ]
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(
            normalized,
            [
                {
                    "role": "tool",
                    "tool_call_id": "toolu_789",
                    "content": "command output"
                },
                {
                    "role": "user",
                    "content": "이 결과를 바탕으로 다음 단계 진행해 주세요."
                }
            ]
        )

    def test_text_only_content_blocks_remain_plain_messages(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "안녕하세요."},
                    {"type": "text", "text": "계속 진행해 주세요."}
                ]
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(
            normalized,
            [
                {
                    "role": "user",
                    "content": "안녕하세요.계속 진행해 주세요."
                }
            ]
        )

    def test_invalid_dict_response_is_rejected_in_non_streaming_transform(self) -> None:
        with self.assertRaisesRegex(ValueError, "OpenAI-compatible"):
            self.handler.handle_non_streaming_response(
                {
                    "model": "ollama-cloud:kimi-k2.5",
                    "message": {"role": "assistant", "content": "bad"},
                    "done": True
                },
                "ollama-cloud:kimi-k2.5"
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

        self.assertEqual(response["content"], [{"type": "text", "text": "정상 응답입니다."}])
        self.assertEqual(response["stop_reason"], "end_turn")


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
                'data: [DONE]\n\n',
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(resp, "ollama-cloud:kimi-k2.5", "req_text")
        )

        joined = "".join(chunks)
        self.assertIn("안녕하세요", joined)
        self.assertIn('event: message_stop', joined)

    def test_stream_uses_message_content_when_delta_content_is_missing(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{},"message":{"content":"반갑습니다."},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                'data: [DONE]\n\n',
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(resp, "ollama-cloud:kimi-k2.5", "req_msg")
        )

        joined = "".join(chunks)
        self.assertIn("반갑습니다.", joined)
        self.assertIn('event: message_stop', joined)

    def test_stream_uses_reasoning_content_when_standard_text_is_missing(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"reasoning_content":"먼저 변경 사항을 확인했습니다."},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                'data: [DONE]\n\n',
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(resp, "ollama-cloud:kimi-k2.5", "req_reasoning")
        )

        joined = "".join(chunks)
        self.assertIn("먼저 변경 사항을 확인했습니다.", joined)
        self.assertIn('event: message_stop', joined)

    def test_stream_logs_warning_for_empty_end_turn_response(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                'data: [DONE]\n\n',
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

        self.assertIn('event: message_stop', "".join(chunks))
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
        self.assertTrue(any("[DONE] 없이 스트림 종료" in message for message in logs.output))

    def test_stream_logs_warning_when_generator_is_closed(self) -> None:
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"text":"첫 청크"},"finish_reason":null}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                'data: [DONE]\n\n',
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
                'data: [DONE]\n\n',
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
        self.assertIn('event: message_stop', joined)


if __name__ == "__main__":
    unittest.main()
