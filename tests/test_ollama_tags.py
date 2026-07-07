import unittest
from unittest.mock import patch

from app import create_app


class OllamaTagsRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        token = app.config.get("PROXY_API_TOKEN", "")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def test_tags_returns_dynamic_models(self) -> None:
        fake_entries = [
            {
                "name": "opencode:glm-5.2",
                "model": "opencode:glm-5.2",
                "context_length": 205000,
            }
        ]
        with patch(
            "src.utils.model_catalog.list_model_entries_for_tags",
            return_value=fake_entries,
        ):
            response = self.client.get("/api/tags", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["models"], fake_entries)


if __name__ == "__main__":
    unittest.main()