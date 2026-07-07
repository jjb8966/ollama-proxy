import unittest

from src.utils.message_compaction import (
    apply_compaction_round,
    build_compacted_request,
    estimate_request_tokens,
)


class MessageCompactionTests(unittest.TestCase):
    def test_estimate_request_tokens_counts_text_and_tools(self) -> None:
        tokens = estimate_request_tokens(
            {
                "messages": [{"role": "user", "content": "hello world"}],
                "tools": [{"type": "function", "function": {"name": "Bash"}}],
            }
        )
        self.assertGreater(tokens, 1)

    def test_round_zero_truncates_large_tool_output(self) -> None:
        messages = [
            {"role": "user", "content": "run"},
            {"role": "tool", "tool_call_id": "call_1", "content": "x" * 12000},
            {"role": "user", "content": "next"},
        ]
        compacted, changed = apply_compaction_round(messages, 0)
        self.assertTrue(changed)
        self.assertLess(len(compacted[1]["content"]), 12000)

    def test_round_one_drops_oldest_messages_but_keeps_tail(self) -> None:
        messages = [
            {"role": "system", "content": "sys"},
            *[
                {"role": "user", "content": f"msg-{index}"}
                for index in range(12)
            ],
        ]
        compacted, changed = apply_compaction_round(messages, 1)
        self.assertTrue(changed)
        self.assertLess(len(compacted), len(messages))
        self.assertEqual(compacted[0]["content"], "sys")
        self.assertEqual(compacted[-1]["content"], "msg-11")

    def test_build_compacted_request_sets_round_counter(self) -> None:
        req = {
            "model": "opencode:glm-5.2",
            "messages": [
                {"role": "user", "content": "a"},
                {"role": "tool", "tool_call_id": "call_1", "content": "x" * 12000},
                {"role": "user", "content": "b"},
            ],
        }
        compacted_req = build_compacted_request(req, 0)
        self.assertIsNotNone(compacted_req)
        assert compacted_req is not None
        self.assertEqual(compacted_req["_compaction_round"], 1)
        self.assertLess(
            len(compacted_req["messages"][1]["content"]),
            len(req["messages"][1]["content"]),
        )


if __name__ == "__main__":
    unittest.main()
