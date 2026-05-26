# composer-2.5 × Claude Code 수정 정리

Claude Code에서 `cursor:composer-2.5`가 도구 사용부터 최종 응답까지 정상 동작하도록 수정한 내용을 정리한 문서입니다.

---

## 전체 구조

Claude Code는 Anthropic API 형식으로 요청하고, 실제 흐름은 다음과 같습니다.

```
Claude Code
  → ollama-proxy (/v1/messages, Anthropic SSE)
    → cursor-api-proxy (/v1/chat/completions, OpenAI SSE)
      → Cursor CLI (composer-2.5)
```

문제는 **한 군데가 아니라 두 프록시 + 모델 동작**이 겹친 것이었습니다.

---

## 문제 1: tool JSON이 텍스트로도 노출됨

### 증상

모델이 `{"name":"Bash","arguments":{"command":"ls -la"}}` 같은 JSON을 출력하면, Claude Code 화면에 **일반 텍스트**로도 보이고 **tool_use**로도 보였습니다.

### 원인

`cursor-api-proxy`가 assistant 텍스트를 그대로 스트리밍한 뒤, 끝에서 같은 내용을 tool call로 다시 emit했습니다.

### 수정

**파일:** `cursor-api-proxy/src/lib/chat-stream-tools.ts`

- 응답이 `{` 또는 ` ``` ` 로 시작하면 tool JSON일 가능성이 있으므로 텍스트 버퍼링
- 스트림 종료 시 `resolveToolCalls()`로 tool call이 확인되면 버퍼 폐기, tool만 emit
- tool call이 없으면 버퍼를 일반 텍스트로 flush

---

## 문제 2: OpenAI tool index 충돌 → Read/Glob이 한 블록에 섞임

### 증상 (가장 치명적)

ollama-proxy 로그에 이런 패턴이 보였습니다.

- tool block **시작**: `Read`
- tool block **종료**: `Glob`

Claude Code 입장에서는 `Read`인데 인자는 `Glob`용이라 **엉뚱한 도구 실행** 또는 validation error가 발생했습니다.

### 원인

`cursor-api-proxy`의 `writeOpenAiToolCallChunks()`가 tool을 emit할 때마다 **index를 항상 0부터** 다시 썼습니다.

`ollama-proxy`는 OpenAI `tool_calls[].index`로 Anthropic block을 매핑하는데, 서로 다른 tool이 같은 index 0으로 오면 **같은 Anthropic block에 name/args가 덮어씌워집니다**.

### 수정

**파일:** `cursor-api-proxy/src/lib/openai-stream-finish.ts`

- `writeOpenAiToolCallChunks(ctx, toolCalls, startIndex)`에 `startIndex` 추가
- emitter가 `nextIndex`를 유지해 **Read=0, Glob=1**처럼 분리

```typescript
let nextIndex = 0;
// ...
writeOpenAiToolCallChunks(ctx, [call], nextIndex);
nextIndex += 1;
```

---

## 문제 3: Bash/Read 같은 도구를 무한 반복 (max_turns)

### 증상

- **Bash:** `ls -la`를 6~8턴 반복, `result_len: 0`, `error_max_turns`
- **Read:** `Read {}` 빈 인자로 반복, `file_path` missing

### 원인 A — 대화 히스토리가 Cursor CLI prompt에 안 들어감

`buildPromptFromMessages()`가 assistant의 `tool_calls`와 tool result를 prompt에 넣지 않았습니다. 모델은 “내가 이미 Bash를 썼다”는 걸 모르고 매 턴 다시 호출했습니다.

### 수정 A

**파일:** `cursor-api-proxy/src/lib/openai.ts`

- assistant `tool_calls` → `[tool_use Bash {...}]` 형태로 prompt에 포함
- tool result → `Tool result: ...` 형태로 포함
- tool result 직후에는 “같은 도구 반복하지 말라”는 hint 추가

### 원인 B — compact 모드에서 required 파라미터 누락

도구가 8개 넘으면 `toolsToSystemText()`가 이름+짧은 설명만 넣고 **parameters 스키마를 빼버렸습니다**. 모델이 `Read`에 `file_path`가 필수인지 몰라 `{}`로 호출.

### 수정 B

**파일:** `cursor-api-proxy/src/lib/openai.ts`

- compact 모드에서도 `- Read(file_path*, offset, limit): 설명`처럼 required 표시

### 원인 C — 중복 호출 차단이 약함

`priorToolCallSignatures`만으로는 `path` vs `file_path`를 다른 호출로 봤고, 빈 args `{}` 반복도 막지 못했습니다.

### 수정 C

**파일:** `cursor-api-proxy/src/lib/extract-tool-calls.ts`, `chat-stream-tools.ts`

- `collectFailedToolNames()`: 이전 turn에서 validation error 난 도구 이름 수집
- `isInvalidEmptyToolCall()`: schema에 required가 있는데 `{}`면 차단
- `toolCallSignature()`에서 `path→file_path`, `search_term→query` alias 후 비교
- `filterAlreadyCalled()`로 스트림 종료 시 한 번에 필터

---

## 문제 4: Read 인자 이름 불일치 (`path` vs `file_path`)

### 증상

```
InputValidationError: The required parameter `file_path` is missing
An unexpected parameter `path` was provided
```

composer-2.5는 OpenAI/Cursor 스타일로 `path`를 쓰고, Claude Code `Read`는 `file_path`만 받습니다.

### 원인 (2단계)

1. **ollama-proxy:** 종료 시에만 `path→file_path` 정규화했는데, **이미 raw `{"path":...}` delta를 Claude Code에 보냄**
2. **cursor-api-proxy:** signature 비교 시 alias 없음

### 수정

**ollama-proxy** (`src/handlers/anthropic.py`):

- `_normalize_tool_input()`에 `path → file_path` alias
- 스트리밍 중 즉시 flush하지 않고, `close_open_blocks()`에서 정규화 후 한 번에 delta 전송

**cursor-api-proxy** (`src/lib/extract-tool-calls.ts`):

- `toolCallSignature()`에서도 동일 alias 적용

---

## 문제 5: WebSearch 자동 추론 → 무한 대기

### 증상

벤치마크/조사 질문에서 WebSearch가 자동 호출되고, upstream(opencode 등) billing 문제로 **“Crunching...” 무한 대기**.

### 원인

`inferToolCallsFromResearchIntent()`가 연구 의도만으로 WebSearch를 자동 생성.

### 수정

**파일:** `cursor-api-proxy/src/lib/extract-tool-calls.ts`, `chat-stream-tools.ts`, `openai.ts`

- `inferToolCallsFromResearchIntent()` → 항상 `[]` 반환
- `emitEarlyResearchToolCalls()` → no-op
- `dropUnmentionedWebTools()`로 사용자가 이름을 안 붙이면 WebSearch/WebFetch 차단

---

## 문제 6: native tool call을 너무 일찍 emit

### 증상

첫 Read는 성공했는데, 이미 만든 요약 텍스트 뒤에 **같은 Read를 또 tool_use로 붙여** max_turns.

### 원인

Cursor CLI가 name-only delta를 먼저 보내고 arguments는 나중에 오는데, **첫 delta만 보고 바로 emit**하면 full args 기준 중복 검사가 불가능.

### 수정

**파일:** `cursor-api-proxy/src/lib/chat-stream-tools.ts`

- 스트리밍 중 native tool call은 **즉시 emit하지 않음**
- `nativeToolCalls`에만 누적
- 스트림 종료 시 `filterAlreadyCalled()` 후 한 번만 emit

---

## 문제 7: ollama-proxy tool block/index (이전 수정, 여전히 중요)

### 증상

- Invalid tool parameters
- tool argument animation 없음
- args가 다른 block으로 흩어짐

### 수정

**파일:** `ollama-proxy/src/handlers/anthropic.py`

- `tool_openai_index_to_block`로 OpenAI index ↔ Anthropic block 고정
- `input_json_delta`를 4바이트 chunk로 쪼개 UI animation
- `search_term → query` alias
- text block을 tool block 전에 닫기

---

## 추가 반영: ollama-proxy 최종 보강

이번 문서를 기준으로 `ollama-proxy` 쪽에 남아 있던 스트리밍 변환 문제를 다시 확인하고 보강했습니다.

### 파일별 반영 내용

**파일:** `ollama-proxy/src/handlers/anthropic.py`

- OpenAI 계열 `call_*` tool id를 Claude Code가 기대하는 `toolu_*` 형식으로 정규화
- `_normalize_tool_input()`에서 tool schema를 기준으로 `path → file_path`, `search_term → query` alias 적용
- OpenAI `tool_calls[].index`와 Anthropic `content_block.index`를 `tool_openai_index_to_block`으로 분리해 매핑
- tool name만 먼저 오고 arguments가 나중에 오는 Cursor CLI 스타일 스트림을 같은 tool block으로 누적
- text block이 열린 상태에서 tool call이 시작되면 text block을 먼저 닫도록 처리
- tool arguments를 raw 상태로 즉시 flush하지 않고, `close_open_blocks()`에서 정규화한 뒤 `input_json_delta`로 전송
- `input_json_delta`를 4글자 단위로 분할해 Claude Code의 tool argument 표시가 움직이도록 처리

**파일:** `ollama-proxy/src/handlers/chat.py`

- Cursor provider 요청 시 tools가 있으면 `X-Cursor-Mode: ask`, tools가 없으면 `X-Cursor-Mode: agent` 헤더 전송
- 도구가 있는 Claude Code 요청에서는 Cursor가 직접 도구를 실행하지 않고 tool JSON을 반환하게 함

**파일:** `ollama-proxy/tests/test_anthropic_handler.py`

- SSE `data:` 이벤트를 파싱하는 테스트 헬퍼 추가
- 여러 `input_json_delta` 조각을 재조립해 최종 tool input JSON을 검증
- name chunk와 arguments chunk가 같은 OpenAI index로 들어올 때 하나의 Anthropic tool block에 유지되는지 회귀 테스트 추가
- optional 빈 필드(`pages: ""`)가 스트리밍 flush 전에 제거되는지 최종 tool input 기준으로 검증

### 검증

```bash
PYTHONPATH=. ./venv/bin/pytest tests/test_anthropic_handler.py -q
```

결과:

```text
27 passed in 0.13s
```

---

## 검증했던 결과 (수정 후)

| 테스트 | 결과 |
|--------|------|
| Bash (`pwd`) | `is_error: False`, 2 turns, `end_turn` |
| Read (`src/handlers/anthropic.py`) | `is_error: False`, 2 turns, 실제 파일 읽고 요약 |
| WebSearch 자동 추론 | `tools: []` (차단됨) |
| 프록시 단독 `say OK` | 정상 응답 |

---

## “응답 자체를 안 한다” — 가능한 원인

프록시 단독 호출은 되므로, **Claude Code 인터랙티브 + 도구 사용** 조합에서만 막힐 수 있습니다.

1. **스트림이 끝나지 않음**  
   native tool call을 끝까지 모아 emit하도록 바꿨기 때문에, Cursor CLI 스트림이 hang되면 tool도 text도 안 나갑니다.

2. **버퍼링이 과하게 동작**  
   응답이 `{`로 시작하면 전부 버퍼링합니다. tool JSON이 아닌데 `{`로 시작하는 prose면, 끝날 때까지 화면에 아무것도 안 보일 수 있습니다.

3. **필터가 너무 강함**  
   `filterAlreadyCalled` + `isInvalidEmptyToolCall` + `failedToolNames`가 겹치면, 모델이 보낸 tool call이 전부 걸러지고 `tool_use` 없이 `end_turn`만 가거나, 빈 응답처럼 보일 수 있습니다.

4. **컨테이너 미반영**  
   로컬 파일은 수정됐는데 `cursor-api-proxy` / `ollama-proxy` 컨테이너가 예전 이미지면 증상이 그대로입니다.

---

## 수정 파일 요약

| 파일 | 역할 |
|------|------|
| `cursor-api-proxy/src/lib/openai-stream-finish.ts` | tool index 연속 증가 |
| `cursor-api-proxy/src/lib/chat-stream-tools.ts` | JSON 버퍼링, 중복/빈 args 차단, native emit 지연 |
| `cursor-api-proxy/src/lib/extract-tool-calls.ts` | WebSearch 비활성, signature alias, failed tool 추적 |
| `cursor-api-proxy/src/lib/openai.ts` | prompt에 tool history, compact required 표시 |
| `ollama-proxy/src/handlers/anthropic.py` | call_* id 정규화, path→file_path, search_term→query, delayed args flush, stream mapping |
| `ollama-proxy/src/handlers/chat.py` | Cursor tools 요청 시 ask mode 헤더 적용 |
| `ollama-proxy/tests/test_anthropic_handler.py` | SSE tool delta 재조립 및 스트리밍 도구 입력 회귀 테스트 |

---

## 관련 프로젝트 경로

- ollama-proxy: `/Users/jbj/Desktop/work/my/project/ollama-proxy`
- cursor-api-proxy: `/Users/jbj/Desktop/work/my/project/cursor-api-proxy`

## Claude Code 설정 (검증 시 사용)

```json
{
  "ANTHROPIC_BASE_URL": "http://127.0.0.1:5002",
  "ANTHROPIC_DEFAULT_SONNET_MODEL": "cursor:composer-2.5",
  "ANTHROPIC_DEFAULT_HAIKU_MODEL": "cli-proxy-api:gpt-5.5"
}
```

---

*작성일: 2026-05-24*
