import unittest
from unittest.mock import patch

from app import create_app


class OllamaRouteReasoningFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        token = app.config.get("PROXY_API_TOKEN", "")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def test_non_streaming_dict_response_uses_reasoning_when_content_is_empty(
        self,
    ) -> None:
        with patch("src.routes.ollama.ChatHandler") as mock_chat_handler:
            mock_chat_handler.return_value.handle_chat_request.return_value = {
                "choices": [{"message": {"content": "", "reasoning": "ok"}}]
            }

            response = self.client.post(
                "/api/chat",
                headers={**self.headers, "Content-Type": "application/json"},
                json={
                    "model": "ollama-cloud:minimax-m2.7",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["message"]["content"], "ok")
