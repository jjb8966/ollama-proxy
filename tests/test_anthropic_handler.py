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
                    # CCR-style: list content는 JSON.stringify로 직렬화됨
                    "content": json.dumps(
                        [{"type": "text", "text": "command output"}],
                        ensure_ascii=False,
                    ),
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
            normalized,
            [{"role": "user", "content": "안녕하세요.\n계속 진행해 주세요."}],
        )

    def test_user_text_before_and_after_tool_result_are_split_into_separate_messages(
        self,
    ) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "before"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "done",
                    },
                    {"type": "text", "text": "after"},
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(
            normalized,
            [
                {"role": "user", "content": "before"},
                {"role": "tool", "tool_call_id": "toolu_1", "content": "done"},
                {"role": "user", "content": "after"},
            ],
        )

    def test_tool_use_missing_id_gets_deterministic_fallback(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "search", "input": {"q": "x"}},
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(
            normalized[0]["tool_calls"][0]["id"],
            "toolu_ollama_fallback_0_0",
        )

    def test_tool_result_unserializable_content_fallback(self) -> None:
        circular: dict = {}
        circular["self"] = circular

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": circular,
                    }
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(
            normalized,
            [
                {
                    "role": "tool",
                    "tool_call_id": "toolu_1",
                    "content": "[unserializable content]",
                }
            ],
        )

    def test_tool_result_preserves_non_text_result_blocks(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_search_1",
                        "content": [
                            {
                                "type": "web_search_result",
                                "title": "OpenAI",
                                "url": "https://openai.com/",
                            }
                        ],
                    }
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertIn("web_search_result", normalized[0]["content"])
        self.assertIn("https://openai.com/", normalized[0]["content"])

    def test_server_tool_use_is_preserved_as_tool_call(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "server_tool_use",
                        "id": "toolu_server_search_1",
                        "name": "web_search",
                        "input": {"query": "Claude Code WebSearch"},
                    }
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        tool_call = normalized[0]["tool_calls"][0]
        self.assertEqual(tool_call["id"], "toolu_server_search_1")
        self.assertEqual(tool_call["function"]["name"], "WebSearch")
        self.assertEqual(
            json.loads(tool_call["function"]["arguments"]),
            {"query": "Claude Code WebSearch"},
        )

    def test_web_search_tool_result_is_preserved_as_tool_message(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "web_search_tool_result",
                        "tool_use_id": "toolu_server_search_1",
                        "content": [
                            {
                                "type": "web_search_result",
                                "title": "Claude Code",
                                "url": "https://claude.com/code",
                            }
                        ],
                    }
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(normalized[0]["role"], "tool")
        self.assertEqual(normalized[0]["tool_call_id"], "toolu_server_search_1")
        self.assertIn("Claude Code", normalized[0]["content"])
        self.assertIn("https://claude.com/code", normalized[0]["content"])

    def test_assistant_advisor_tool_result_preserved_as_text(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "advisor_tool_result",
                        "tool_use_id": "toolu_a1",
                        "content": {"type": "advisor_result", "text": "prior advice"},
                    }
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(normalized[0]["role"], "assistant")
        self.assertIn("prior advice", normalized[0]["content"])

    def test_user_advisor_tool_result_becomes_tool_message(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "advisor_tool_result",
                        "tool_use_id": "toolu_a1",
                        "content": {"type": "advisor_result", "text": "advice text"},
                    }
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(normalized[0]["role"], "tool")
        self.assertEqual(normalized[0]["tool_call_id"], "toolu_a1")
        self.assertEqual(normalized[0]["content"], "advice text")

    def test_assistant_advisor_tool_result_error_preserved_as_text(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "advisor_tool_result_error",
                        "tool_use_id": "toolu_err",
                        "content": {"type": "advisor_error", "message": "upstream failed"},
                    }
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(normalized[0]["role"], "assistant")
        self.assertIn("upstream failed", normalized[0]["content"])

    def test_user_base64_image_block_converts_to_image_url_content(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "이 이미지를 설명해 주세요."},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "ZmFrZS1pbWFnZS1kYXRh",
                        },
                    },
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(
            normalized,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "이 이미지를 설명해 주세요."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,ZmFrZS1pbWFnZS1kYXRh"
                            },
                        },
                    ],
                }
            ],
        )

    def test_user_image_block_before_tool_result_is_preserved(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": "YWJjMTIz",
                        },
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_img_1",
                        "content": "tool output",
                    },
                ],
            }
        ]

        normalized = self.handler._normalize_messages(messages)

        self.assertEqual(
            normalized,
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/jpeg;base64,YWJjMTIz"
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "toolu_img_1",
                    "content": "tool output",
                },
            ],
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
                "model": "cli-proxy-api:gpt-5.4",
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
            "cli-proxy-api:gpt-5.4",
        )

        self.assertEqual(
            response["content"], [{"type": "text", "text": "정상 응답입니다."}]
        )
        self.assertEqual(response["stop_reason"], "end_turn")

    def test_non_streaming_response_prunes_optional_empty_tool_fields(self) -> None:
        tools_contract = {
            "Read": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "pages": {"type": "string"},
                    },
                    "required": ["file_path"],
                },
                "required": {"file_path"},
                "properties": {
                    "file_path": {"type": "string"},
                    "pages": {"type": "string"},
                },
            }
        }
        response = self.handler.handle_non_streaming_response(
            {
                "model": "cli-proxy-api:gpt-5.4",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "toolu_read_1",
                                    "type": "function",
                                    "function": {
                                        "name": "Read",
                                        "arguments": json.dumps(
                                            {"file_path": "/tmp/a.txt", "pages": ""},
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
            "cli-proxy-api:gpt-5.4",
            tools_contract=tools_contract,
        )

        self.assertEqual(
            response["content"][0]["input"],
            {"file_path": "/tmp/a.txt"},
        )
        self.assertEqual(response["stop_reason"], "tool_use")

    def test_normalize_tool_input_prunes_nested_optional_empty_fields(self) -> None:
        tool_contract = {
            "schema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "tag": {"type": "string"},
                            "mode": {"type": "string"},
                        },
                        "required": ["mode"],
                    },
                },
                "required": ["prompt"],
            },
            "required": {"prompt"},
            "properties": {
                "prompt": {"type": "string"},
                "metadata": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "mode": {"type": "string"},
                    },
                    "required": ["mode"],
                },
            },
        }

        normalized = self.handler._normalize_tool_input(
            {
                "prompt": "조사",
                "metadata": {
                    "tag": "   ",
                    "mode": "quick",
                },
                "pages": "",
            },
            tool_contract,
        )

        self.assertEqual(
            normalized,
            {
                "prompt": "조사",
                "metadata": {"mode": "quick"},
            },
        )

    def test_normalize_tool_input_keeps_required_empty_fields(self) -> None:
        tool_contract = {
            "schema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["prompt"],
            },
            "required": {"prompt"},
            "properties": {
                "prompt": {"type": "string"},
                "description": {"type": "string"},
            },
        }

        normalized = self.handler._normalize_tool_input(
            {"prompt": "", "description": " "},
            tool_contract,
        )

        self.assertEqual(normalized, {"prompt": ""})

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

    def test_normalize_tools_maps_server_web_search_to_function_tool(self) -> None:
        normalized = self.handler._normalize_tools(
            [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                }
            ]
        )

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["type"], "function")
        self.assertEqual(normalized[0]["function"]["name"], "WebSearch")
        self.assertEqual(
            normalized[0]["function"]["parameters"],
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )

    def test_normalize_tools_deduplicates_web_search_aliases(self) -> None:
        normalized = self.handler._normalize_tools(
            [
                {
                    "name": "WebSearch",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                },
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                },
            ]
        )

        self.assertEqual(
            [tool["function"]["name"] for tool in normalized],
            ["WebSearch"],
        )

    def test_extract_tools_contract_uses_web_search_canonical_name(self) -> None:
        contracts = self.handler._extract_tools_contract(
            [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                }
            ]
        )

        self.assertIn("WebSearch", contracts)
        self.assertNotIn("web_search", contracts)
        self.assertEqual(contracts["WebSearch"]["required"], {"query"})

    def test_normalize_tool_choice_maps_web_search_alias(self) -> None:
        normalized = self.handler._normalize_tool_choice(
            {"type": "tool", "name": "web_search"}
        )

        self.assertEqual(
            normalized,
            {"type": "function", "function": {"name": "WebSearch"}},
        )

    def test_normalize_tool_input_maps_web_search_aliases_to_contract_field(self) -> None:
        search_term_contract = {
            "schema": {
                "type": "object",
                "properties": {"search_term": {"type": "string"}},
                "required": ["search_term"],
            },
            "required": {"search_term"},
            "properties": {"search_term": {"type": "string"}},
        }
        search_term_input = self.handler._normalize_tool_input(
            {"query": "gpt-5.5 latest", "searchTerm": "duplicate"},
            search_term_contract,
        )

        search_term_camel_contract = {
            "schema": {
                "type": "object",
                "properties": {"searchTerm": {"type": "string"}},
                "required": ["searchTerm"],
            },
            "required": {"searchTerm"},
            "properties": {"searchTerm": {"type": "string"}},
        }
        search_term_camel_input = self.handler._normalize_tool_input(
            {"query": "gpt-5.5 latest", "search_term": "duplicate"},
            search_term_camel_contract,
        )

        self.assertEqual(search_term_input, {"search_term": "gpt-5.5 latest"})
        self.assertEqual(search_term_camel_input, {"searchTerm": "gpt-5.5 latest"})

    def test_normalize_tool_input_prunes_empty_web_search_domains(self) -> None:
        tool_contract = {
            "schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "allowed_domains": {"type": "array", "items": {"type": "string"}},
                    "blocked_domains": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
            },
            "required": {"query"},
            "properties": {
                "query": {"type": "string"},
                "allowed_domains": {"type": "array", "items": {"type": "string"}},
                "blocked_domains": {"type": "array", "items": {"type": "string"}},
            },
        }

        normalized = self.handler._normalize_tool_input(
            {
                "query": "OpenAI official website",
                "allowed_domains": ["openai.com"],
                "blocked_domains": [],
            },
            tool_contract,
        )

        self.assertEqual(
            normalized,
            {
                "query": "OpenAI official website",
                "allowed_domains": ["openai.com"],
            },
        )

    def test_non_streaming_response_maps_web_search_alias_to_websearch(self) -> None:
        response = self.handler.handle_non_streaming_response(
            {
                "model": "cli-proxy-api:gpt-5.5",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_search_1",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": json.dumps(
                                            {"query": "gpt-5.5 latest"},
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
            "cli-proxy-api:gpt-5.5",
        )

        self.assertEqual(response["stop_reason"], "tool_use")
        self.assertEqual(response["content"][0]["name"], "WebSearch")
        self.assertEqual(response["content"][0]["input"], {"query": "gpt-5.5 latest"})

    def test_map_stop_reason_accepts_tool_reason_aliases(self) -> None:
        for finish_reason in ("tool_calls", "tool_call", "function_call", "tool_use"):
            self.assertEqual(self.handler._map_stop_reason(finish_reason), "tool_use")


class AnthropicHandlerThinkingMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = AnthropicHandler()

    def test_map_thinking_enabled_high_budget(self) -> None:
        effort = self.handler._map_anthropic_thinking_to_reasoning_effort(
            {"thinking": {"type": "enabled", "budget_tokens": 9000}}
        )
        self.assertEqual(effort, "high")

    def test_map_thinking_adaptive_xhigh(self) -> None:
        effort = self.handler._map_anthropic_thinking_to_reasoning_effort(
            {
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": "xhigh"},
            }
        )
        self.assertEqual(effort, "high")

    def test_map_thinking_disabled(self) -> None:
        effort = self.handler._map_anthropic_thinking_to_reasoning_effort(
            {"thinking": {"type": "disabled"}}
        )
        self.assertIsNone(effort)

    def test_build_proxy_request_includes_reasoning_effort(self) -> None:
        proxied = self.handler.build_proxy_request(
            {
                "model": "cursor:composer-2.5",
                "stream": True,
                "thinking": {"type": "enabled", "budget_tokens": 9000},
                "messages": [{"role": "user", "content": "hello"}],
            }
        )

        self.assertEqual(proxied.get("reasoning_effort"), "high")
        self.assertIn("_tools_contract", proxied)


class AnthropicHandlerStreamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = AnthropicHandler()

    @staticmethod
    def _stream(lines):
        for line in lines:
            yield line

    @staticmethod
    def _sse_events(chunks):
        events = []
        for chunk in chunks:
            for packet in chunk.split("\n\n"):
                for line in packet.splitlines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
        return events

    @staticmethod
    def _tool_input_json(events, block_index):
        return "".join(
            event["delta"]["partial_json"]
            for event in events
            if event.get("type") == "content_block_delta"
            and event.get("index") == block_index
            and event.get("delta", {}).get("type") == "input_json_delta"
        )

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
                "cli-proxy-api:gpt-5.4",
                "req_null_tool_calls",
            )
        )

        joined = "".join(chunks)
        self.assertIn("안녕하세요", joined)
        self.assertIn("event: message_stop", joined)

    def test_stream_keeps_tool_arguments_on_same_openai_index(self) -> None:
        args = json.dumps({"search_term": "gpt-5.5 pricing benchmark"}, ensure_ascii=False)
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"role":"assistant","tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"WebSearch","arguments":""}}]},"finish_reason":null}]}\n\n',
                f'data: {{"choices":[{{"delta":{{"tool_calls":[{{"index":0,"function":{{"arguments":{json.dumps(args)}}}}}]}},"finish_reason":null}}]}}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(
                resp,
                "cursor:composer-2.5",
                "req_tool_args_same_index",
            )
        )

        events = self._sse_events(chunks)
        tool_start = next(
            event
            for event in events
            if event.get("type") == "content_block_start"
            and event.get("content_block", {}).get("type") == "tool_use"
        )
        tool_input = json.loads(self._tool_input_json(events, tool_start["index"]))

        self.assertEqual(tool_start["content_block"]["name"], "WebSearch")
        self.assertEqual(tool_input, {"search_term": "gpt-5.5 pricing benchmark"})

    def test_stream_maps_web_search_alias_to_websearch_tool_block(self) -> None:
        args = json.dumps({"query": "gpt-5.5 latest"}, ensure_ascii=False)
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_search_1","type":"function","function":{"name":"web_search","arguments":""}}]},"finish_reason":null}]}\n\n',
                f'data: {{"choices":[{{"delta":{{"tool_calls":[{{"index":0,"function":{{"arguments":{json.dumps(args)}}}}}]}}}}]}}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"tool_use"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(
                resp,
                "cli-proxy-api:gpt-5.5",
                "req_web_search_alias",
            )
        )

        events = self._sse_events(chunks)
        tool_start = next(
            event
            for event in events
            if event.get("type") == "content_block_start"
            and event.get("content_block", {}).get("type") == "tool_use"
        )
        tool_input = json.loads(self._tool_input_json(events, tool_start["index"]))
        message_delta = next(
            event for event in events if event.get("type") == "message_delta"
        )

        self.assertEqual(tool_start["content_block"]["name"], "WebSearch")
        self.assertEqual(tool_input, {"query": "gpt-5.5 latest"})
        self.assertEqual(message_delta["delta"]["stop_reason"], "tool_use")

    def test_stream_maps_query_to_search_term_with_websearch_contract(self) -> None:
        args = json.dumps({"query": "Claude Code WebSearch"}, ensure_ascii=False)
        tools_contract = {
            "WebSearch": {
                "schema": {
                    "type": "object",
                    "properties": {"search_term": {"type": "string"}},
                    "required": ["search_term"],
                },
                "required": {"search_term"},
                "properties": {"search_term": {"type": "string"}},
            }
        }
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_search_1","type":"function","function":{"name":"web_search","arguments":""}}]},"finish_reason":null}]}\n\n',
                f'data: {{"choices":[{{"delta":{{"tool_calls":[{{"index":0,"function":{{"arguments":{json.dumps(args)}}}}}]}}}}]}}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(
                resp,
                "cli-proxy-api:gpt-5.5",
                "req_web_search_contract",
                tools_contract=tools_contract,
            )
        )

        events = self._sse_events(chunks)
        tool_start = next(
            event
            for event in events
            if event.get("type") == "content_block_start"
            and event.get("content_block", {}).get("type") == "tool_use"
        )
        tool_input = json.loads(self._tool_input_json(events, tool_start["index"]))

        self.assertEqual(tool_start["content_block"]["name"], "WebSearch")
        self.assertEqual(tool_input, {"search_term": "Claude Code WebSearch"})

    def test_stream_prunes_optional_empty_tool_fields_before_flushing_json(self) -> None:
        tools_contract = {
            "Read": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "pages": {"type": "string"},
                    },
                    "required": ["file_path"],
                },
                "required": {"file_path"},
                "properties": {
                    "file_path": {"type": "string"},
                    "pages": {"type": "string"},
                },
            }
        }
        tool_call_payload = json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "toolu_read_1",
                                    "type": "function",
                                    "function": {
                                        "name": "Read",
                                        "arguments": json.dumps(
                                            {
                                                "file_path": "/tmp/a.txt",
                                                "pages": "",
                                            },
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            ensure_ascii=False,
        )
        resp = self._stream(
            [
                f"data: {tool_call_payload}\n\n",
                'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        chunks = list(
            self.handler.stream_anthropic_response(
                resp,
                "cli-proxy-api:gpt-5.4",
                "req_stream_prune",
                tools_contract=tools_contract,
            )
        )

        events = self._sse_events(chunks)
        tool_start = next(
            event
            for event in events
            if event.get("type") == "content_block_start"
            and event.get("content_block", {}).get("type") == "tool_use"
        )
        tool_input = json.loads(self._tool_input_json(events, tool_start["index"]))

        self.assertEqual(tool_start["content_block"]["name"], "Read")
        self.assertEqual(tool_input, {"file_path": "/tmp/a.txt"})
        self.assertTrue(any(event.get("type") == "message_stop" for event in events))

    def test_stream_flushes_tool_arguments_before_stream_end(self) -> None:
        args_part1 = '{"file_path":'
        args_part2 = '"/tmp/a.txt"}'
        resp = self._stream(
            [
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"Read","arguments":""}}]},"finish_reason":null}]}\n\n',
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "function": {"arguments": args_part1},
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ]
                    }
                )
                + "\n\n",
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "function": {"arguments": args_part2},
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ]
                    }
                )
                + "\n\n",
                'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

        stream = self.handler.stream_anthropic_response(
            resp,
            "cursor:composer-2.5",
            "req_incremental_tool_args",
        )
        saw_partial_args = False
        all_chunks = []
        for chunk in stream:
            all_chunks.append(chunk)
            joined = "".join(all_chunks)
            if "input_json_delta" in chunk and "message_stop" not in joined:
                saw_partial_args = True
                break

        self.assertTrue(
            saw_partial_args,
            "tool argument deltas should stream before message_stop",
        )


if __name__ == "__main__":
    unittest.main()
