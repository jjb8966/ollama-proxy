# Fix: GPT 5.4 "Invalid tool parameters" 에러 수정

## TL;DR

> **Quick Summary**: Claude Code → ollama-proxy → cli-proxy-api-gpt:gpt-5.4 경로에서 `AnthropicHandler._sanitize_tool_input_schema()`가 비표준 JSON Schema 키워드(`additionalProperties`, `title`, `default`, `$schema` 등)를 필터링하지 않고 그대로 백엔드에 전달하여 "Invalid tool parameters" 에러가 발생합니다. Google 프로바이더의 allowlist 패턴을 차용하여 범용 스키마 정리를 적용합니다.
> 
> **Deliverables**:
> - `AnthropicHandler._sanitize_tool_input_schema()` 강화 (allowlist 기반)
> - 단위 테스트 추가
> 
> **Estimated Effort**: Quick
> **Parallel Execution**: NO - sequential (2개 task)
> **Critical Path**: Task 1 → Task 2

---

## Context

### Original Request
Claude Code에서 ollama-proxy의 GPT 5.4 모델을 호출하면 아주 높은 확률로 "Invalid tool parameters" 에러가 발생하는 문제를 수정해달라는 요청.

### Interview Summary
**Key Discussions**:
- "Invalid tool parameters" 문자열이 프록시 코드베이스에 없음 → 업스트림 백엔드에서 반환하는 에러
- `AnthropicHandler._sanitize_tool_input_schema()`가 알 수 없는 키를 모두 `sanitized[key] = value`로 통과시킴
- 반면 `GoogleApiClient._sanitize_schema_for_google()`는 `_ALLOWED_SCHEMA_KEYS` allowlist로 엄격하게 필터링

**Research Findings**:
- Claude Code가 보내는 도구 정의에는 `additionalProperties: false`, `title`, `default`, `$schema`, `format`, `pattern` 등 확장 JSON Schema 키워드가 포함됨
- 이런 키워드들은 OpenAI 공식 API에서도 일부만 지원하며, 비표준 백엔드에서는 거부되는 경우가 빈번
- `additionalProperties`는 유효한 JSON Schema 키워드이나 다수의 비-OpenAI 백엔드가 미지원

### Metis Review
**Identified Gaps** (addressed):
- 실제 에러 응답 본문 미확인 → **자동 해결**: 원인이 코드 레벨에서 명확하므로 로그 확인 없이 allowlist 패턴 적용
- `additionalProperties` 처리 방안 → **기본값 적용**: 제거 (Google과 동일 전략)
- 범위 확장 가능성 → **가드레일 설정**: `AnthropicHandler`만 수정, `ChatHandler` 확장은 제외
- 기존 동작 파괴 가능성 → **테스트 추가**: 단위 테스트로 변경 전후 동작 검증

---

## Work Objectives

### Core Objective
`_sanitize_tool_input_schema()`에 allowlist 기반 필터링을 추가하여 비표준 JSON Schema 키워드가 백엔드로 전달되지 않도록 합니다.

### Concrete Deliverables
- `src/handlers/anthropic.py`: `_sanitize_tool_input_schema()` 함수 수정
- `tests/test_anthropic_handler.py`: 스키마 정리 단위 테스트 추가

### Definition of Done
- [x] 비표준 JSON Schema 키워드(`additionalProperties`, `title`, `default`, `$schema`, `format`, `pattern` 등)가 정리된 스키마로 변환됨
- [x] 표준 키워드(`type`, `description`, `enum`, `properties`, `items`, `required`, `anyOf`, `oneOf`, `allOf`)가 보존됨
- [x] 기존 테스트가 모두 통과
- [x] 새 테스트가 모두 통과

### Must Have
- allowlist 기반 필터링 (`_ALLOWED_SCHEMA_KEYS` 패턴)
- 재귀적 정리 (중첩된 `properties`, `items`, `anyOf`/`oneOf`/`allOf` 내부까지)
- 기존 동작과의 호환성

### Must NOT Have (Guardrails)
- `GoogleApiClient._sanitize_schema_for_google()` 수정 금지 — Google은 자체 sanitization이 있음
- `ChatHandler` 레벨 공통 정리 함수 도입 금지 — 이번 스코프 밖
- 새로운 추상화 레이어 생성 금지
- `_normalize_tools()` 함수의 전체 구조 변경 금지

---

## Verification Strategy (MANDATORY)

> **UNIVERSAL RULE: ZERO HUMAN INTERVENTION**
>
> ALL tasks in this plan MUST be verifiable WITHOUT any human action.

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: YES (Tests-after)
- **Framework**: unittest (기존 패턴 유지)

### Agent-Executed QA Scenarios (MANDATORY — ALL tasks)

**Verification Tool by Deliverable Type:**

| Type | Tool | How Agent Verifies |
|------|------|-------------------|
| **Library/Module** | Bash (python unittest) | Run tests, compare output |

---

## Execution Strategy

### Sequential Execution

```
Task 1 (Start Immediately):
└── _sanitize_tool_input_schema() 강화

Task 2 (After Task 1):
└── 단위 테스트 추가 및 전체 테스트 실행

Critical Path: Task 1 → Task 2
```

### Dependency Matrix

| Task | Depends On | Blocks | Can Parallelize With |
|------|------------|--------|---------------------|
| 1 | None | 2 | None |
| 2 | 1 | None | None |

### Agent Dispatch Summary

| Wave | Tasks | Recommended Agents |
|------|-------|-------------------|
| 1 | 1, 2 | task(category="quick", load_skills=[], run_in_background=false) |

---

## TODOs

- [x] 1. `_sanitize_tool_input_schema()` allowlist 기반 필터링 적용

  **What to do**:
  - `src/handlers/anthropic.py` 파일 상단(클래스 외부)에 allowlist 상수를 정의:
    ```python
    _ALLOWED_TOOL_SCHEMA_KEYS = {
        "type",
        "description",
        "enum",
        "items",
        "properties",
        "required",
        "nullable",
        "anyOf",
        "oneOf",
        "allOf",
    }
    ```
  - `_sanitize_tool_input_schema()` 메서드의 마지막 `sanitized[key] = value` 라인 **앞에** allowlist 체크를 추가:
    ```python
    # 기존 코드: sanitized[key] = value
    # 변경: allowlist에 없는 키는 무시
    if key not in _ALLOWED_TOOL_SCHEMA_KEYS:
        continue
    sanitized[key] = value
    ```
  - 이미 `properties`, `items`, `anyOf`, `oneOf`, `allOf` 키는 위에서 개별 처리 후 `continue`하므로, 마지막 fallback에서 allowlist 체크만 추가하면 됨
  - **주의**: `allOf` 키가 현재 `anyOf`, `oneOf`과 함께 처리되고 있으므로 allowlist에도 포함해야 함 (이미 개별 처리됨, 중복 통과 방지)

  **Must NOT do**:
  - `GoogleApiClient._sanitize_schema_for_google()` 수정
  - `_normalize_tools()` 함수의 전체 구조 변경
  - Google의 대문자 타입 변환(`STRING`, `OBJECT` 등) 추가 — 이는 Google 전용
  - `ChatHandler` 레벨 수정

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 단일 파일의 단일 함수에 allowlist 상수 추가 및 조건문 1줄 추가
  - **Skills**: []
    - 별도 스킬 불필요

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential
  - **Blocks**: Task 2
  - **Blocked By**: None

  **References** (CRITICAL):

  **Pattern References** (existing code to follow):
  - `src/providers/google.py:22-59` — `_UNSUPPORTED_CONSTRAINT_KEYS`, `_UNSUPPORTED_SCHEMA_KEYS`, `_ALLOWED_SCHEMA_KEYS` 상수 정의 패턴. 이 allowlist 접근법을 차용하되, 범용 프로바이더용으로 더 허용적인 목록 사용
  - `src/providers/google.py:77-141` — `_sanitize_schema_for_google()` 함수. allowlist 기반 재귀적 스키마 정리의 전체 구현 참조

  **API/Type References** (contracts to implement against):
  - `src/handlers/anthropic.py:262-302` — 현재 `_sanitize_tool_input_schema()` 구현. 이 함수의 295번째 줄 `sanitized[key] = value` 앞에 allowlist 체크를 삽입

  **WHY Each Reference Matters**:
  - `google.py:22-59`: allowlist 상수 네이밍 패턴과 어떤 키를 허용/차단하는지의 기준을 보여줌
  - `google.py:77-141`: 재귀적 스키마 정리가 어떤 순서로 동작하는지 참조 (properties → items → anyOf/oneOf → fallback)
  - `anthropic.py:262-302`: 수정 대상. 현재 fallback에서 모든 키를 통과시키는 `sanitized[key] = value`가 문제의 핵심

  **Acceptance Criteria**:

  **Agent-Executed QA Scenarios (MANDATORY):**

  ```
  Scenario: 비표준 키워드가 제거되는지 확인
    Tool: Bash (python)
    Preconditions: 프로젝트 디렉토리에서 실행
    Steps:
      1. python3 -c "
         from src.handlers.anthropic import AnthropicHandler
         schema = {
           'type': 'object',
           'properties': {
             'name': {'type': 'string', 'title': 'Name', 'default': 'test'},
             'age': {'type': 'integer', 'format': 'int32'}
           },
           'required': ['name'],
           'additionalProperties': False,
           '$schema': 'http://json-schema.org/draft-07/schema#',
           'title': 'PersonSchema'
         }
         result = AnthropicHandler._sanitize_tool_input_schema(schema)
         assert 'additionalProperties' not in result, f'additionalProperties found: {result}'
         assert 'title' not in result, f'title found in root: {result}'
         assert '$schema' not in result, f'schema found: {result}'
         assert 'title' not in result['properties']['name'], f'title found in prop: {result}'
         assert 'default' not in result['properties']['name'], f'default found: {result}'
         assert 'format' not in result['properties']['age'], f'format found: {result}'
         assert result['type'] == 'object'
         assert result['required'] == ['name']
         assert result['properties']['name']['type'] == 'string'
         assert result['properties']['age']['type'] == 'integer'
         print('PASS: 비표준 키워드 제거 확인')
         "
      2. Assert: stdout contains "PASS: 비표준 키워드 제거 확인"
    Expected Result: 비표준 키워드가 제거되고 표준 키워드만 유지
    Evidence: stdout 캡처

  Scenario: 표준 키워드가 보존되는지 확인
    Tool: Bash (python)
    Preconditions: 프로젝트 디렉토리에서 실행
    Steps:
      1. python3 -c "
         from src.handlers.anthropic import AnthropicHandler
         schema = {
           'type': 'object',
           'description': 'A test schema',
           'properties': {
             'items': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of items'},
             'choice': {'anyOf': [{'type': 'string'}, {'type': 'integer'}]}
           },
           'required': ['items'],
           'enum': ['a', 'b']
         }
         result = AnthropicHandler._sanitize_tool_input_schema(schema)
         assert result['type'] == 'object'
         assert result['description'] == 'A test schema'
         assert result['required'] == ['items']
         assert 'enum' in result
         assert result['properties']['items']['type'] == 'array'
         assert result['properties']['items']['items'] == {'type': 'string'}
         assert len(result['properties']['choice']['anyOf']) == 2
         print('PASS: 표준 키워드 보존 확인')
         "
      2. Assert: stdout contains "PASS: 표준 키워드 보존 확인"
    Expected Result: 모든 표준 JSON Schema 키워드가 보존됨
    Evidence: stdout 캡처
  ```

  **Commit**: YES
  - Message: `fix(anthropic): sanitize tool input schema with allowlist to prevent Invalid tool parameters`
  - Files: `src/handlers/anthropic.py`
  - Pre-commit: `python -m pytest tests/test_anthropic_handler.py -v`

---

- [x] 2. 단위 테스트 추가 및 전체 테스트 실행

  **What to do**:
  - `tests/test_anthropic_handler.py`에 `_sanitize_tool_input_schema` 테스트 클래스 추가:
    - 비표준 키워드 제거 테스트 (`additionalProperties`, `title`, `default`, `$schema`, `format`, `pattern`, `examples`, `$defs`, `definitions`, `$ref`, `const`, `$id`, `$comment`)
    - 표준 키워드 보존 테스트 (`type`, `description`, `enum`, `properties`, `items`, `required`, `nullable`, `anyOf`, `oneOf`, `allOf`)
    - 중첩된 스키마에서의 재귀 정리 테스트 (properties 내부, items 내부, anyOf 내부)
    - 빈 스키마 / 비-dict 입력 처리 테스트
    - `_normalize_tools()` 통합 테스트: Anthropic 형식 도구 정의에서 비표준 키워드가 최종 OpenAI 형식에서도 제거되는지 확인
  - 전체 테스트 실행하여 기존 테스트와의 호환성 확인

  **Must NOT do**:
  - 기존 테스트 수정
  - 불필요하게 많은 테스트 추가 (핵심 케이스만)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 기존 테스트 파일에 테스트 케이스 추가하는 단순 작업
  - **Skills**: []
    - 별도 스킬 불필요

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (Task 1 이후)
  - **Blocks**: None
  - **Blocked By**: Task 1

  **References** (CRITICAL):

  **Pattern References** (existing code to follow):
  - `tests/test_anthropic_handler.py:1-60` — 기존 테스트 패턴 (unittest, setUp, assertEqual 사용)

  **API/Type References** (contracts to implement against):
  - `src/handlers/anthropic.py:262-302` — 테스트 대상 함수
  - `src/handlers/anthropic.py:304-329` — `_normalize_tools()` 통합 테스트 대상

  **WHY Each Reference Matters**:
  - `test_anthropic_handler.py:1-60`: 테스트 클래스 구조, import 패턴, assertion 스타일을 보여줌
  - `anthropic.py:262-302`: 테스트할 함수의 정확한 인터페이스와 반환값
  - `anthropic.py:304-329`: `_normalize_tools()`가 `_sanitize_tool_input_schema()`를 호출하는 방식

  **Acceptance Criteria**:

  **Agent-Executed QA Scenarios (MANDATORY):**

  ```
  Scenario: 새 테스트 통과 확인
    Tool: Bash (python -m pytest)
    Preconditions: Task 1 완료, 프로젝트 디렉토리에서 실행
    Steps:
      1. python -m pytest tests/test_anthropic_handler.py -v --tb=short
      2. Assert: exit code 0
      3. Assert: stdout contains "PASSED" for all new test methods
      4. Assert: stdout does NOT contain "FAILED"
    Expected Result: 모든 테스트 통과
    Evidence: pytest 출력 캡처

  Scenario: 전체 테스트 스위트 회귀 확인
    Tool: Bash (python -m pytest)
    Preconditions: Task 1 완료, 프로젝트 디렉토리에서 실행
    Steps:
      1. python -m pytest tests/ -v --tb=short
      2. Assert: exit code 0
      3. Assert: stdout does NOT contain "FAILED"
      4. Assert: stdout does NOT contain "ERROR"
    Expected Result: 기존 테스트 포함 모든 테스트 통과
    Evidence: pytest 출력 캡처
  ```

  **Commit**: YES (Task 1과 함께)
  - Message: `test(anthropic): add unit tests for tool input schema sanitization`
  - Files: `tests/test_anthropic_handler.py`
  - Pre-commit: `python -m pytest tests/ -v`

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 1 | `fix(anthropic): sanitize tool input schema with allowlist to prevent Invalid tool parameters` | `src/handlers/anthropic.py` | `python -m pytest tests/test_anthropic_handler.py -v` |
| 2 | `test(anthropic): add unit tests for tool input schema sanitization` | `tests/test_anthropic_handler.py` | `python -m pytest tests/ -v` |

---

## Success Criteria

### Verification Commands
```bash
# 전체 테스트 통과
python -m pytest tests/ -v  # Expected: all passed, 0 failed

# 스키마 정리 확인 (inline)
python3 -c "
from src.handlers.anthropic import AnthropicHandler
schema = {'type': 'object', 'properties': {'q': {'type': 'string', 'title': 'Q'}}, 'additionalProperties': False, 'title': 'T'}
result = AnthropicHandler._sanitize_tool_input_schema(schema)
assert 'additionalProperties' not in result
assert 'title' not in result
assert 'title' not in result['properties']['q']
print('SUCCESS')
"  # Expected: SUCCESS
```

### Final Checklist
- [x] 비표준 JSON Schema 키워드가 필터링됨
- [x] 표준 키워드(`type`, `description`, `enum`, `properties`, `items`, `required`, `nullable`, `anyOf`, `oneOf`, `allOf`)가 보존됨
- [x] 기존 테스트 전체 통과 (38 passed)
- [x] 새 테스트 전체 통과 (20 passed)
- [x] Google 프로바이더 코드 미수정
- [x] ChatHandler 코드 미수정
- [x] LSP diagnostics clean (0 errors, 0 warnings)
