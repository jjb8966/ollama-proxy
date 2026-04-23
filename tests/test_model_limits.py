from src.utils.model_limits import get_model_limits, reset_model_limits_cache


EXPECTED_CONTEXT_LENGTH = 256000
EXPECTED_CODEX_CONTEXT_LENGTH = 400000
EXPECTED_CODEX_MAX_OUTPUT_TOKENS = 128000


def test_ollama_cloud_gemma4_31b_model_limits_are_loaded() -> None:
    reset_model_limits_cache()

    limits = get_model_limits("ollama-cloud:gemma4:31b")

    assert limits is not None
    assert limits.context_length == EXPECTED_CONTEXT_LENGTH
    assert limits.max_output_tokens == EXPECTED_CONTEXT_LENGTH


def test_ollama_alias_resolves_to_ollama_cloud_gemma4_31b_limits() -> None:
    reset_model_limits_cache()

    limits = get_model_limits("ollama:gemma4:31b")

    assert limits is not None
    assert limits.context_length == EXPECTED_CONTEXT_LENGTH
    assert limits.max_output_tokens == EXPECTED_CONTEXT_LENGTH


def test_ollama_cloud_kimi_k2_6_model_limits_are_loaded() -> None:
    reset_model_limits_cache()

    limits = get_model_limits("ollama-cloud:kimi-k2.6")

    assert limits is not None
    assert limits.context_length == EXPECTED_CONTEXT_LENGTH
    assert limits.max_output_tokens == EXPECTED_CONTEXT_LENGTH


def test_gpt_5_3_codex_high_model_limits_are_loaded() -> None:
    reset_model_limits_cache()

    limits = get_model_limits("cli-proxy-api:gpt-5.3-codex-high")

    assert limits is not None
    assert limits.context_length == EXPECTED_CODEX_CONTEXT_LENGTH
    assert limits.max_output_tokens == EXPECTED_CODEX_MAX_OUTPUT_TOKENS


def test_gpt_5_3_codex_xhigh_model_limits_are_loaded() -> None:
    reset_model_limits_cache()

    limits = get_model_limits("cli-proxy-api:gpt-5.3-codex-xhigh")

    assert limits is not None
    assert limits.context_length == EXPECTED_CODEX_CONTEXT_LENGTH
    assert limits.max_output_tokens == EXPECTED_CODEX_MAX_OUTPUT_TOKENS
