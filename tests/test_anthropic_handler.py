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


if __name__ == "__main__":
    unittest.main()
