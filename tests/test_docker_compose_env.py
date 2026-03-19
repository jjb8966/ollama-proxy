from pathlib import Path


def test_cli_proxy_api_gpt_env_is_forwarded_to_container() -> None:
    compose_file = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    compose_text = compose_file.read_text(encoding="utf-8")

    assert "- CLI_PROXY_API_GPT_KEYS=${CLI_PROXY_API_GPT_KEYS}" in compose_text
    assert (
        "- CLI_PROXY_API_GPT_BASE_URL="
        "${CLI_PROXY_API_GPT_BASE_URL:-https://jjb8966.duckdns.org/cli-proxy-api-gpt/v1}"
    ) in compose_text
