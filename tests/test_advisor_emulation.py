# -*- coding: utf-8 -*-
import json
import os
import unittest
from unittest.mock import patch

from src.utils.advisor_emulation import (
    DEFAULT_ADVISOR_MODEL,
    build_advisor_error_block,
    build_advisor_result_block,
    extract_openai_completion_text,
    find_advisor_tool_use_id,
    has_advisor_tool,
    is_advisor_forced_request,
    resolve_advisor_model,
)


class AdvisorEmulationTests(unittest.TestCase):

    def test_has_advisor_tool_detects_advisor_in_tools(self) -> None:
        self.assertTrue(
            has_advisor_tool(
                {"tools": [{"name": "advisor", "input_schema": {"type": "object"}}]}
            )
        )
        self.assertFalse(
            has_advisor_tool(
                {"tools": [{"name": "bash", "input_schema": {"type": "object"}}]}
            )
        )
        self.assertFalse(has_advisor_tool({"messages": []}))

    def test_is_advisor_forced_request_requires_tool_choice(self) -> None:
        base = {
            "tools": [{"name": "advisor", "input_schema": {"type": "object"}}],
            "messages": [{"role": "user", "content": "hi"}],
        }
        self.assertFalse(is_advisor_forced_request(base))
        self.assertTrue(
            is_advisor_forced_request(
                {**base, "tool_choice": {"type": "tool", "name": "advisor"}}
            )
        )
        self.assertFalse(
            is_advisor_forced_request(
                {**base, "tool_choice": {"type": "tool", "name": "bash"}}
            )
        )
        self.assertFalse(
            is_advisor_forced_request(
                {**base, "tool_choice": {"type": "any"}}
            )
        )

    def test_resolve_advisor_model_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADVISOR_MODEL", None)
            self.assertEqual(resolve_advisor_model(), DEFAULT_ADVISOR_MODEL)

    def test_resolve_advisor_model_from_env(self) -> None:
        with patch.dict(os.environ, {"ADVISOR_MODEL": "cursor:composer-2.5"}):
            self.assertEqual(resolve_advisor_model(), "cursor:composer-2.5")

    def test_find_advisor_tool_use_id_from_assistant_blocks(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_adv_42",
                        "name": "advisor",
                        "input": {},
                    }
                ],
            }
        ]
        self.assertEqual(find_advisor_tool_use_id(messages), "toolu_adv_42")

    def test_find_advisor_tool_use_id_fallback_when_missing(self) -> None:
        self.assertTrue(find_advisor_tool_use_id(None).startswith("srvtoolu_"))
        self.assertTrue(
            find_advisor_tool_use_id(
                [{"role": "user", "content": "no tool use here"}]
            ).startswith("srvtoolu_")
        )

    def test_build_advisor_result_block(self) -> None:
        block = build_advisor_result_block("toolu_1", "hello world")
        self.assertEqual(block["type"], "advisor_tool_result")
        self.assertEqual(block["tool_use_id"], "toolu_1")
        self.assertEqual(
            block["content"], {"type": "advisor_result", "text": "hello world"}
        )

    def test_build_advisor_error_block(self) -> None:
        block = build_advisor_error_block("toolu_e", "timeout")
        self.assertEqual(block["type"], "advisor_tool_result_error")
        self.assertEqual(block["tool_use_id"], "toolu_e")
        self.assertEqual(
            block["content"], {"type": "advisor_error", "message": "timeout"}
        )

    def test_extract_openai_completion_text_string_content(self) -> None:
        resp = {
            "choices": [
                {"message": {"role": "assistant", "content": "plain text response"}}
            ]
        }
        self.assertEqual(
            extract_openai_completion_text(resp), "plain text response"
        )

    def test_extract_openai_completion_text_list_content(self) -> None:
        resp = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": "안녕하세요",
                            }
                        ],
                    }
                }
            ]
        }
        self.assertEqual(extract_openai_completion_text(resp), "안녕하세요")

    def test_extract_openai_completion_text_handles_none(self) -> None:
        self.assertEqual(extract_openai_completion_text(None), "")
        self.assertEqual(extract_openai_completion_text({}), "")


if __name__ == "__main__":
    unittest.main()
