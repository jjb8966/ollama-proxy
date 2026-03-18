import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
