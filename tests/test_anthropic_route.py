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


if __name__ == "__main__":
    unittest.main()
