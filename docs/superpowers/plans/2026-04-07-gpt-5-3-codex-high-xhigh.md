# GPT-5.3 Codex High/XHigh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cli-proxy-api:gpt-5.3-codex-high`와 `cli-proxy-api:gpt-5.3-codex-xhigh`를 모델 목록과 모델 제한 로더에서 인식되도록 추가합니다.

**Architecture:** 모델 목록과 제한 값의 단일 소스는 `models.json`이므로, 새 모델 2개를 같은 형식으로 여기에 추가합니다. 로직 코드는 바꾸지 않고 `src/utils/model_limits.py`의 기존 로더가 새 항목을 읽는지만 테스트로 고정합니다.

**Tech Stack:** Python, pytest, JSON configuration

---

## File Structure

- `models.json`
  - 모델 목록과 context/output 한도의 단일 소스입니다.
  - `cli-proxy-api:gpt-5.3-codex` 바로 아래에 high/xhigh 엔트리 2개를 추가합니다.
- `tests/test_model_limits.py`
  - `models.json` 기반 제한 로더가 새 모델을 읽는지 검증합니다.
  - 기존 `get_model_limits()` 테스트 패턴에 맞춰 high/xhigh 조회 테스트를 추가합니다.

### Task 1: Add GPT-5.3 Codex High/XHigh Model Entries

**Files:**
- Modify: `models.json:33-38`
- Modify: `tests/test_model_limits.py:1-24`
- Test: `tests/test_model_limits.py`

- [ ] **Step 1: Write the failing tests**

```python
from src.utils.model_limits import get_model_limits, reset_model_limits_cache


EXPECTED_CONTEXT_LENGTH = 400000
EXPECTED_MAX_OUTPUT_TOKENS = 128000


def test_gpt_5_3_codex_high_model_limits_are_loaded() -> None:
    reset_model_limits_cache()

    limits = get_model_limits("cli-proxy-api:gpt-5.3-codex-high")

    assert limits is not None
    assert limits.context_length == EXPECTED_CONTEXT_LENGTH
    assert limits.max_output_tokens == EXPECTED_MAX_OUTPUT_TOKENS


def test_gpt_5_3_codex_xhigh_model_limits_are_loaded() -> None:
    reset_model_limits_cache()

    limits = get_model_limits("cli-proxy-api:gpt-5.3-codex-xhigh")

    assert limits is not None
    assert limits.context_length == EXPECTED_CONTEXT_LENGTH
    assert limits.max_output_tokens == EXPECTED_MAX_OUTPUT_TOKENS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model_limits.py -v`
Expected: FAIL because `get_model_limits("cli-proxy-api:gpt-5.3-codex-high")` and `get_model_limits("cli-proxy-api:gpt-5.3-codex-xhigh")` return `None`

- [ ] **Step 3: Write minimal implementation**

```json
{
  "name": "cli-proxy-api:gpt-5.3-codex",
  "model": "cli-proxy-api:gpt-5.3-codex",
  "context_length": 400000,
  "max_output_tokens": 128000
},
{
  "name": "cli-proxy-api:gpt-5.3-codex-high",
  "model": "cli-proxy-api:gpt-5.3-codex-high",
  "context_length": 400000,
  "max_output_tokens": 128000
},
{
  "name": "cli-proxy-api:gpt-5.3-codex-xhigh",
  "model": "cli-proxy-api:gpt-5.3-codex-xhigh",
  "context_length": 400000,
  "max_output_tokens": 128000
}
```

```python
from src.utils.model_limits import get_model_limits, reset_model_limits_cache


EXPECTED_CONTEXT_LENGTH = 400000
EXPECTED_MAX_OUTPUT_TOKENS = 128000


def test_gpt_5_3_codex_high_model_limits_are_loaded() -> None:
    reset_model_limits_cache()

    limits = get_model_limits("cli-proxy-api:gpt-5.3-codex-high")

    assert limits is not None
    assert limits.context_length == EXPECTED_CONTEXT_LENGTH
    assert limits.max_output_tokens == EXPECTED_MAX_OUTPUT_TOKENS


def test_gpt_5_3_codex_xhigh_model_limits_are_loaded() -> None:
    reset_model_limits_cache()

    limits = get_model_limits("cli-proxy-api:gpt-5.3-codex-xhigh")

    assert limits is not None
    assert limits.context_length == EXPECTED_CONTEXT_LENGTH
    assert limits.max_output_tokens == EXPECTED_MAX_OUTPUT_TOKENS
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_model_limits.py -v`
Expected: PASS for the existing gemma4 tests and the new codex high/xhigh tests

- [ ] **Step 5: Run focused regression check**

Run: `pytest tests/test_anthropic_route.py -v`
Expected: PASS with no behavior changes, confirming the new model entries do not affect the current Anthropic route contract tests

- [ ] **Step 6: Commit**

```bash
git add models.json tests/test_model_limits.py
git commit -m "$(cat <<'EOF'
modify: gpt 5.3 codex high xhigh 모델 추가

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

## Self-Review

- Spec coverage: 요청한 범위인 모델명 추가를 `models.json`과 `tests/test_model_limits.py` 한 쌍으로 모두 커버합니다. 추가 라우팅 로직이나 provider 변경은 포함하지 않습니다.
- Placeholder scan: `TBD`, `TODO`, 모호한 지시 없이 실제 코드와 명령을 모두 포함했습니다.
- Type consistency: 새 모델 이름은 문서 전반에서 `cli-proxy-api:gpt-5.3-codex-high`, `cli-proxy-api:gpt-5.3-codex-xhigh`로 일관되게 사용합니다.
