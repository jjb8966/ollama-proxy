import unittest
from unittest.mock import Mock, patch

from src.utils.model_catalog import (
    extract_upstream_model_ids,
    list_model_entries_for_tags,
    load_available_models,
    reset_model_catalog_cache,
)


class _DummyRotator:
    def __init__(self, keys=None) -> None:
        self.provider = "Dummy"
        self.api_keys = keys if keys is not None else ["key-a"]

    def get_next_key(self) -> str:
        if not self.api_keys:
            return ""
        return self.api_keys[0]


class _DummyApiConfig:
    def __init__(self) -> None:
        self.antigravity_rotator = _DummyRotator()
        self.opencode_rotator = _DummyRotator()


class ExtractUpstreamModelIdsTests(unittest.TestCase):
    def test_openai_data_ids(self) -> None:
        payload = {"data": [{"id": "gpt-4"}, {"id": "gpt-4o"}]}
        self.assertEqual(extract_upstream_model_ids(payload), ["gpt-4", "gpt-4o"])

    def test_models_array_with_name(self) -> None:
        payload = {"models": [{"name": "llama3"}, {"model": "mistral"}]}
        self.assertEqual(extract_upstream_model_ids(payload), ["llama3", "mistral"])


class FetchOpenAICompatibleModelsTests(unittest.TestCase):
    def test_calls_models_endpoint_with_bearer(self) -> None:
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"data": [{"id": "glm-5.2"}]}

        with patch("src.utils.model_catalog.requests.get", return_value=response) as mock_get:
            from src.utils.model_catalog import _fetch_openai_compatible_models

            models = _fetch_openai_compatible_models(
                "https://opencode.ai/zen/go/v1",
                "test-key",
            )

        self.assertEqual(models, ["glm-5.2"])
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        self.assertIn("/models", call_kwargs[0][0])
        self.assertEqual(
            call_kwargs[1]["headers"]["Authorization"],
            "Bearer test-key",
        )


class ListModelEntriesForTagsTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_model_catalog_cache()

    def tearDown(self) -> None:
        reset_model_catalog_cache()

    def test_merges_providers_into_proxy_model_ids(self) -> None:
        api_config = _DummyApiConfig()

        def fake_fetch(provider: str, _api_config):
            if provider == "antigravity":
                return ["gcli-gemini-3-pro-preview"]
            if provider == "opencode":
                return ["glm-5.2"]
            return []

        with patch(
            "src.utils.model_catalog._fetch_provider_upstream_models",
            side_effect=fake_fetch,
        ):
            entries = list_model_entries_for_tags(api_config)

        ids = [entry["model"] for entry in entries]
        self.assertIn("antigravity:gcli-gemini-3-pro-preview", ids)
        self.assertIn("opencode:glm-5.2", ids)
        for entry in entries:
            self.assertEqual(entry["name"], entry["model"])

    def test_load_available_models_alias(self) -> None:
        api_config = _DummyApiConfig()

        def fake_fetch(provider: str, _api_config):
            if provider == "opencode":
                return ["glm-5.2"]
            return []

        with patch(
            "src.utils.model_catalog._fetch_provider_upstream_models",
            side_effect=fake_fetch,
        ):
            entries = load_available_models(api_config)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["model"], "opencode:glm-5.2")


if __name__ == "__main__":
    unittest.main()