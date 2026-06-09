import json
import unittest
from unittest.mock import patch

from src.handlers.anthropic import AnthropicHandler

from flask import Flask

from src.core.errors import ProxyRequestError
from src.routes.anthropic import anthropic_bp


class AnthropicRouteErrorHandlingTests(unittest.TestCase):
    def setUp(self) -> None:
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["api_config"] = object()
        app.register_blueprint(anthropic_bp)
        self.client = app.test_client()

    def test_streaming_context_error_returns_anthropic_error_body(self) -> None:
        with patch("src.routes.anthropic.ChatHandler") as mock_chat_handler:
            mock_chat_handler.return_value.handle_chat_request.return_value = ProxyRequestError(
                model="ollama-cloud:kimi-k2.5",
                message="context window exceeded",
                status_code=400,
                error_type="invalid_request_error"
            )
            response = self.client.post(
                "/v1/messages",
                json={
                    "model": "ollama-cloud:kimi-k2.5",
                    "stream": True,
                    "messages": [{"role": "user", "content": "hi"}]
                }
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.mimetype, "application/json")
        body = response.get_json()
        self.assertEqual(body["type"], "error")
        self.assertEqual(body["error"]["type"], "invalid_request_error")
        self.assertEqual(body["error"]["message"], "context window exceeded")

    def test_non_streaming_context_error_returns_anthropic_error_body(self) -> None:
        with patch("src.routes.anthropic.ChatHandler") as mock_chat_handler:
            mock_chat_handler.return_value.handle_chat_request.return_value = ProxyRequestError(
                model="ollama-cloud:kimi-k2.5",
                message="context window exceeded",
                status_code=400,
                error_type="invalid_request_error"
            )
            response = self.client.post(
                "/v1/messages",
                json={
                    "model": "ollama-cloud:kimi-k2.5",
                    "stream": False,
                    "messages": [{"role": "user", "content": "hi"}]
                }
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.mimetype, "application/json")
        body = response.get_json()
        self.assertEqual(body["type"], "error")
        self.assertEqual(body["error"]["message"], "context window exceeded")

    def test_user_image_block_is_forwarded_to_chat_handler(self) -> None:
        with patch("src.routes.anthropic.ChatHandler") as mock_chat_handler:
            mock_chat_handler.return_value.handle_chat_request.return_value = ProxyRequestError(
                model="cli-proxy-api:gpt-5.4-high",
                message="context window exceeded",
                status_code=400,
                error_type="invalid_request_error"
            )
            response = self.client.post(
                "/v1/messages",
                json={
                    "model": "cli-proxy-api:gpt-5.4-high",
                    "stream": False,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "이미지를 설명해 주세요."},
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
                    ],
                },
            )

        proxied_request = mock_chat_handler.return_value.handle_chat_request.call_args.args[0]

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            proxied_request["messages"],
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "이미지를 설명해 주세요."},
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

    def test_build_proxy_request_keeps_internal_tools_contract_out_of_provider_payload(self) -> None:
        handler = AnthropicHandler()
        proxied_request = handler.build_proxy_request(
            {
                "model": "cli-proxy-api:gpt-5.4-high",
                "stream": False,
                "messages": [{"role": "user", "content": "read"}],
                "tools": [
                    {
                        "name": "Read",
                        "description": "Read file",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string"},
                                "pages": {"type": "string"},
                            },
                            "required": ["file_path"],
                        },
                    }
                ],
            }
        )

        self.assertIn("_tools_contract", proxied_request)
        tools_contract = proxied_request.pop("_tools_contract")
        self.assertNotIn("_tools_contract", proxied_request)
        self.assertEqual(tools_contract["Read"]["required"], {"file_path"})
        self.assertIn("pages", tools_contract["Read"]["properties"])
        self.assertEqual(proxied_request["tools"][0]["function"]["name"], "Read")

    def test_route_does_not_inject_or_execute_web_search_locally(self) -> None:
        with patch("src.routes.anthropic.ChatHandler") as mock_chat_handler:
            mock_chat_handler.return_value.handle_chat_request.return_value = ProxyRequestError(
                model="cli-proxy-api:gpt-5.5",
                message="stop after inspecting proxied request",
                status_code=400,
                error_type="invalid_request_error",
            )
            response = self.client.post(
                "/v1/messages",
                json={
                    "model": "cli-proxy-api:gpt-5.5",
                    "stream": False,
                    "messages": [{"role": "user", "content": "최신 정보를 검색해 주세요."}],
                    "tools": [
                        {
                            "name": "WebSearch",
                            "description": "Search the web",
                            "input_schema": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                            },
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            mock_chat_handler.return_value.handle_chat_request.call_count,
            1,
        )
        proxied_request = mock_chat_handler.return_value.handle_chat_request.call_args.args[0]
        system_messages = [
            message
            for message in proxied_request["messages"]
            if message.get("role") == "system"
        ]
        self.assertEqual(system_messages, [])
        self.assertEqual(proxied_request["tools"][0]["function"]["name"], "WebSearch")

    def test_plus_web_search_tool_request_returns_local_search_results(self) -> None:
        mock_response = patch("src.routes.anthropic.requests.get").start()
        self.addCleanup(patch.stopall)
        mock_response.return_value.raise_for_status.return_value = None
        mock_response.return_value.text = (
            '<a class="result__a" href="https://example.com/a">Result A</a>'
            '<a class="result__a" href="https://example.com/b">Result B</a>'
        )

        response = self.client.post(
            "/v1/messages",
            json={
                "model": "cli-proxy-api-plus:gpt-5.5",
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "<query>qwen3.7 max</query>"}],
                    }
                ],
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["content"][0]["type"], "server_tool_use")
        self.assertEqual(body["content"][0]["name"], "web_search")
        self.assertEqual(body["content"][0]["input"]["query"], "qwen3.7 max")
        self.assertEqual(body["content"][1]["type"], "web_search_tool_result")
        self.assertEqual(body["content"][1]["tool_use_id"], body["content"][0]["id"])
        self.assertEqual(
            body["content"][1]["content"],
            [
                {
                    "type": "web_search_result",
                    "title": "Result A",
                    "url": "https://example.com/a",
                },
                {
                    "type": "web_search_result",
                    "title": "Result B",
                    "url": "https://example.com/b",
                },
            ],
        )
        self.assertEqual(body["stop_reason"], "end_turn")
        self.assertEqual(
            body["usage"]["server_tool_use"],
            {"web_search_requests": 1, "web_fetch_requests": 0},
        )

    def test_plus_web_search_stream_reports_server_tool_use(self) -> None:
        mock_response = patch("src.routes.anthropic.requests.get").start()
        self.addCleanup(patch.stopall)
        mock_response.return_value.raise_for_status.return_value = None
        mock_response.return_value.text = (
            '<a class="result__a" href="https://example.com/a">Result A</a>'
        )

        response = self.client.post(
            "/v1/messages",
            json={
                "model": "cli-proxy-api-plus:gpt-5.5",
                "stream": True,
                "source": "web_search_tool",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "<query>qwen3.7 max</query>"}],
                    }
                ],
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        events = []
        for chunk in response.get_data(as_text=True).split("\n\n"):
            data_line = next(
                (line for line in chunk.splitlines() if line.startswith("data: ")),
                None,
            )
            if data_line is not None:
                events.append(json.loads(data_line.removeprefix("data: ")))

        message_start = next(event for event in events if event["type"] == "message_start")
        server_tool_use = next(
            event
            for event in events
            if event["type"] == "content_block_start"
            and event["content_block"]["type"] == "server_tool_use"
        )
        search_result = next(
            event
            for event in events
            if event["type"] == "content_block_start"
            and event["content_block"]["type"] == "web_search_tool_result"
        )
        message_delta = next(event for event in events if event["type"] == "message_delta")

        self.assertEqual(server_tool_use["content_block"]["name"], "web_search")
        self.assertEqual(search_result["content_block"]["tool_use_id"], server_tool_use["content_block"]["id"])
        self.assertEqual(
            search_result["content_block"]["content"],
            [
                {
                    "type": "web_search_result",
                    "title": "Result A",
                    "url": "https://example.com/a",
                }
            ],
        )
        self.assertEqual(
            message_start["message"]["usage"]["server_tool_use"],
            {"web_search_requests": 1, "web_fetch_requests": 0},
        )
        self.assertEqual(
            message_delta["usage"]["server_tool_use"],
            {"web_search_requests": 1, "web_fetch_requests": 0},
        )

    def test_cli_web_search_sampling_request_returns_local_search_results(self) -> None:
        mock_response = patch("src.routes.anthropic.requests.get").start()
        self.addCleanup(patch.stopall)
        mock_response.return_value.raise_for_status.return_value = None
        mock_response.return_value.text = (
            '<a class="result__a" href="https://example.com/qwen">Qwen Result</a>'
        )

        response = self.client.post(
            "/v1/messages",
            json={
                "model": "cli-proxy-api:gpt-5.5",
                "stream": True,
                "messages": [
                    {
                        "role": "user",
                        "content": "Perform a web search for the query: Qwen3 Max official",
                    }
                ],
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                "tool_choice": {"type": "tool", "name": "web_search"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_response.call_args.kwargs["params"],
            {"q": "Qwen3 Max official"},
        )
        events = []
        for chunk in response.get_data(as_text=True).split("\n\n"):
            data_line = next(
                (line for line in chunk.splitlines() if line.startswith("data: ")),
                None,
            )
            if data_line is not None:
                events.append(json.loads(data_line.removeprefix("data: ")))

        message_start = next(event for event in events if event["type"] == "message_start")
        search_result = next(
            event
            for event in events
            if event["type"] == "content_block_start"
            and event["content_block"]["type"] == "web_search_tool_result"
        )

        self.assertEqual(message_start["message"]["model"], "cli-proxy-api:gpt-5.5")
        self.assertEqual(
            search_result["content_block"]["content"],
            [
                {
                    "type": "web_search_result",
                    "title": "Qwen Result",
                    "url": "https://example.com/qwen",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
