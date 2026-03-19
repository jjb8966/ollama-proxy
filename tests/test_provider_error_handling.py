import unittest
from unittest.mock import Mock, patch

from src.core.errors import ErrorHandler, ProxyRequestError
from src.providers.base import BaseApiClient


class _DummyClient(BaseApiClient):
    def __init__(self) -> None:
        super().__init__("DummyProvider")

    def _get_api_key(self):
        return "dummy-key"

    def _on_auth_failure(self) -> bool:
        return False


class _DummyAntigravityClient(BaseApiClient):
    def __init__(self) -> None:
        super().__init__("Antigravity")

    def _get_api_key(self):
        return "proxy-token"

    def _on_auth_failure(self) -> bool:
        return False


class ProviderErrorHandlingTests(unittest.TestCase):
    def test_context_overflow_message_is_detected(self) -> None:
        detected = ErrorHandler.is_context_overflow_response(
            400,
            '{"error":"prompt too long; exceeded max context length by 99 tokens"}',
        )

        self.assertTrue(detected)

    def test_context_overflow_response_does_not_retry_all_keys(self) -> None:
        client = _DummyClient()
        response = Mock()
        response.status_code = 400
        response.text = '{"error":"prompt too long; exceeded max context length by 99 tokens"}'
        response.headers = {}

        with patch("src.providers.base.requests.post", return_value=response) as mock_post:
            result = client.post_request(
                url="https://example.com/v1/chat/completions",
                payload={"model": "ollama-cloud:minimax-m2.5", "messages": [{"role": "user", "content": "hello"}]},
                headers={"Content-Type": "application/json"},
                stream=False,
            )

        self.assertEqual(mock_post.call_count, 1)
        self.assertIsInstance(result, ProxyRequestError)
        assert isinstance(result, ProxyRequestError)
        self.assertEqual(result.error_code, "context_length_exceeded")

    def test_streaming_context_overflow_response_is_normalized_without_retry(self) -> None:
        client = _DummyClient()
        response = Mock()
        response.status_code = 400
        response.text = '{"error":"prompt too long; exceeded max context length by 99 tokens"}'
        response.headers = {}

        with patch("src.providers.base.requests.post", return_value=response) as mock_post:
            result = client.post_request(
                url="https://example.com/v1/chat/completions",
                payload={"model": "ollama-cloud:minimax-m2.5", "messages": [{"role": "user", "content": "hello"}]},
                headers={"Content-Type": "application/json"},
                stream=True,
            )

        self.assertEqual(mock_post.call_count, 1)
        self.assertIsInstance(result, ProxyRequestError)
        assert isinstance(result, ProxyRequestError)
        self.assertEqual(result.error_code, "context_length_exceeded")

    def test_antigravity_upstream_503_is_passed_through_without_retry(self) -> None:
        client = _DummyAntigravityClient()
        response = Mock()
        response.status_code = 503
        response.text = (
            '{"error":{"message":"Upstream is overloaded (capacity exhausted). Please retry later.",'
            '"type":"invalid_request_error","code":"model_capacity_exhausted"}}'
        )
        response.headers = {}

        with patch("src.providers.base.requests.post", return_value=response) as mock_post:
            result = client.post_request(
                url="https://example.com/v1/chat/completions",
                payload={"model": "gcli-gemini-3-pro-preview", "messages": [{"role": "user", "content": "hello"}]},
                headers={"Content-Type": "application/json"},
                stream=False,
            )

        self.assertEqual(mock_post.call_count, 1)
        self.assertIsInstance(result, ProxyRequestError)
        assert isinstance(result, ProxyRequestError)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.error_code, "model_capacity_exhausted")
        self.assertEqual(result.error_type, "invalid_request_error")

    def test_antigravity_unknown_model_400_is_passed_through_without_retry(self) -> None:
        client = _DummyAntigravityClient()
        response = Mock()
        response.status_code = 400
        response.text = (
            '{"error":{"message":"Unknown model: claude-sonnet-4-6",'
            '"type":"invalid_request_error"}}'
        )
        response.headers = {}

        with patch("src.providers.base.requests.post", return_value=response) as mock_post:
            result = client.post_request(
                url="https://example.com/v1/chat/completions",
                payload={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hello"}]},
                headers={"Content-Type": "application/json"},
                stream=False,
            )

        self.assertEqual(mock_post.call_count, 1)
        self.assertIsInstance(result, ProxyRequestError)
        assert isinstance(result, ProxyRequestError)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.message, "Unknown model: claude-sonnet-4-6")


if __name__ == "__main__":
    unittest.main()
