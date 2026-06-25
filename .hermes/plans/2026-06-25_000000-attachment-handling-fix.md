# ollama-proxy 첨부파일 처리 방식 개선 계획

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** ollama-proxy의 첨부파일(Read tool 결과 등) 처리 방식을 claude-code-router(CCR)와 동일하게 수정하여, 큰 파일 첨부 시에도 요청이 거부되지 않고 정상 처리되도록 한다.

**Architecture:** CCR은 Fastify 위에서 동작하며 정확한 tiktoken 토큰 카운팅 + longContext 라우팅을 통해 큰 콘텐츠에 대응한다. ollama-proxy는 Flask 위에서 동작하며 _skip_compaction으로 compaction을 건너뛰어 업스트림 에러를 그대로 전달한다. 핵심 변경은 (1) compaction 제거 후 long-context 라우팅 도입, (2) tool_result content를 CCR처럼 그대로 전달, (3) 토큰 추정 정확도 개선.

**Tech Stack:** Python 3.11, Flask, requests

---

## 조사 결과 요약

### CCR의 첨부파일 처리 메커니즘
1. **Anthropic transformer** (`yN` 클래스): tool_result를 `typeof content == "string" ? content : JSON.stringify(content)`로 그대로 직렬화하여 전달
2. **토큰 카운팅**: tiktoken(cl100k_base) 사용. `FD` 함수로 messages+system+tools의 토큰 합계를 정확하게 계산
3. **Long context 라우팅**: `B6` 함수에서 `longContextThreshold`(기본 60000) 초과 시 `Router.longContext` 모델로 자동 전환
4. **Fallback**: `AN` 함수에서 upstream 에러 발생 시 `fallback` 설정에 따라 다른 모델로 재시도
5. Fastify body limit (기본값), 요청 body를 그대로 통과

### ollama-proxy의 현재 동작
1. **`build_proxy_request`** (anthropic.py:756): Anthropic Messages → OpenAI 형식 변환
   - tool_result → `_tool_result_content_to_text` → text 블록만 추출, fallback 시 JSON 직렬화
   - image → `_normalize_image_block` → image_url 형식으로 변환
   - `_skip_compaction: True` 설정 → compaction 완전히 건너뜀
2. **Compaction** (chat.py:304): `_maybe_compact_request` → `_skip_compaction`이면 None 반환, 아니면 chars/4 토큰 추정 후 임계값(80%) 초과 시 "compaction 필요" 메시지 반환
3. **models.json**: 제공업체별 context_length 정의됨 (예: opencode:kimi-k2.6은 context_length=2000000)
4. Flask `MAX_CONTENT_LENGTH = 1GB` (app.py:50), Gunicorn timeout=600초

### 문제 원인
- Anthropic 라우트에서 `_skip_compaction: True` → compaction 비활성화 → 큰 파일이 포함된 요청이 걸러지지 않고 업스트림으로 전달
- 업스트림 API가 context overflow로 거부 → ollama-proxy가 에러를 그대로 반환
- CCR은 longContext 라우팅으로 모델을 자동 전환하지만, ollama-proxy에는 이 기능이 없음
- 이후 대화 진행 불가능한 이유: tool_result 내용이 메시지 히스토리에 남아있어 후속 요청도 같은 에러 발생

---

## Task 1: tool_result content를 CCR처럼 그대로 전달하도록 수정

**Objective:** `_tool_result_content_to_text`가 text 블록만 추출하는 대신, CCR과 동일하게 content를 그대로 string으로 전달하도록 변경

**Files:**
- Modify: `src/handlers/anthropic.py:253-263`
- Test: `tests/test_anthropic_handler.py`

**Step 1: `_tool_result_content_to_text` 수정**

현재 로직: content가 list일 때 text 블록만 추출, 없으면 safe_json_dumps로 폴백

CCR 로직: `typeof content == "string" ? content : JSON.stringify(content)`

```python
@staticmethod
def _tool_result_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # CCR과 동일하게: string이 아니면 JSON.stringify
    return safe_json_dumps(content, TOOL_RESULT_SERIALIZATION_FALLBACK)
```

기존 `_content_blocks_to_text` 분기를 제거하고, list/object 모두 JSON 직렬화로 통일한다. 이는 CCR이 `JSON.stringify(i.content)`로 처리하는 것과 동일한 동작이다.

**Step 2: 기존 테스트 갱신**

`test_tool_result_preserves_non_text_result_blocks` (test_anthropic_handler.py:215)는 기존에 `_content_blocks_to_text`가 text 블록을 추출하지 못해 `safe_json_dumps`로 넘어가는 케이스. 수정 후에도 `safe_json_dumps` 호출로 동일한 결과가 나와야 한다.

`test_tool_result_follows_assistant_tool_call_without_blank_user_message` (line 11): content가 string이므로 변경 영향 없음.

**Step 3: 테스트 실행**

```bash
cd /Users/jbj/Desktop/work/my/project/ollama-proxy
source .venv/bin/activate
python -m pytest tests/test_anthropic_handler.py -v
```

**Step 4: 커밋**

```bash
git add src/handlers/anthropic.py tests/test_anthropic_handler.py
git commit -m "fix: tool_result content를 CCR과 동일하게 stringify 처리"
```

---

## Task 2: _skip_compaction 제거하고 compaction 로직 개선

**Objective:** Anthropic 라우트에서도 compaction이 동작하도록 `_skip_compaction: True`를 제거하고, compaction이 단순히 에러만 반환하지 않고 CCR처럼 long-context 모델로 라우팅하도록 변경

**Files:**
- Modify: `src/handlers/anthropic.py:774` (_skip_compaction 제거)
- Modify: `src/handlers/chat.py:304-336` (compaction 로직 개선)
- Test: `tests/test_chat_handler_limits.py`

**Step 1: `_skip_compaction` 제거**

`src/handlers/anthropic.py:774`에서 `"_skip_compaction": True` 라인 삭제.

```python
# Before (line 773-774):
            "_tools_contract": self._extract_tools_contract(request_tools),
            "_skip_compaction": True,
# After:
            "_tools_contract": self._extract_tools_contract(request_tools),
```

**Step 2: Compaction 로직을 CCR-style long-context 라우팅으로 변경**

`src/handlers/chat.py`의 `_maybe_compact_request`를 수정하여, 임계값 초과 시 에러를 반환하지 않고 long-context 모델로 라우팅하도록 변경.

`ChatHandler` 클래스에 `LONG_CONTEXT_FALLBACK` 매핑 추가:

```python
# models.json에 정의된 context_length 기반으로, 
# 긴 컨텍스트가 필요한 경우 전환할 fallback 모델 매핑
LONG_CONTEXT_FALLBACK: Dict[str, str] = {
    # provider별 기본 모델 → long context fallback 모델
}
```

`_maybe_compact_request`를 `_maybe_route_long_context`로 리네임하고, 임계값 초과 시 요청 모델을 long-context 모델로 변경하는 로직 추가:

```python
def _maybe_route_long_context(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Compaction 대신 CCR처럼 long-context 모델로 라우팅"""
    requested_model = req.get("model")
    if not isinstance(requested_model, str) or not requested_model:
        return req  # 변경 없음

    limits = get_model_limits(requested_model)
    if limits is None or limits.context_length is None or limits.context_length <= 0:
        return req  # limits 정보 없으면 그대로 통과

    estimated_tokens = self._estimate_request_tokens(req)
    threshold_tokens = int(limits.context_length * self.COMPACTION_THRESHOLD_RATIO)
    
    if estimated_tokens <= threshold_tokens:
        return req  # 정상 범위

    # 임계값 초과: long-context fallback 모델 확인
    long_context_model = self._find_long_context_model(requested_model)
    if long_context_model:
        logging.info(
            "[LongContextRouting] %s → %s (tokens: %d, threshold: %d)",
            requested_model, long_context_model, estimated_tokens, threshold_tokens
        )
        req = dict(req)
        req["model"] = long_context_model
        return req

    # fallback이 없으면 요청 그대로 통과 (CCR도 fallback 없으면 통과)
    logging.warning(
        "[LongContextRouting] fallback 없음, 그대로 전달: model=%s tokens=%d",
        requested_model, estimated_tokens
    )
    return req
```

**Step 3: 모델명 변경을 handle_chat_request에서 반영**

`handle_chat_request`에서 `_maybe_route_long_context` 호출 결과의 모델명 변경을 실제 payload에 적용:

```python
# handle_chat_request 내 (line 760 부근)
if messages:
    self._process_image_content(messages)

routed_req = self._maybe_route_long_context(req)
if isinstance(routed_req, dict):
    req = routed_req
    # 모델명이 변경되었으면 로컬 변수도 갱신
    requested_model = req.get("model", requested_model)
```

**Step 4: _find_long_context_model 구현**

```python
def _find_long_context_model(self, requested_model: str) -> Optional[str]:
    """현재 모델보다 context_length가 더 큰 fallback 모델을 찾는다."""
    current_limits = get_model_limits(requested_model)
    if not current_limits or not current_limits.context_length:
        return None

    provider, model = self._parse_model(requested_model)
    if not provider:
        return None

    # 같은 provider 내에서 context_length가 더 큰 모델 탐색
    all_limits = load_model_limits()
    best_model = None
    best_length = current_limits.context_length

    for model_name, limits in all_limits.items():
        if not limits.context_length or limits.context_length <= best_length:
            continue
        p, _ = self._parse_model(model_name)
        if p == provider:
            best_length = limits.context_length
            best_model = model_name

    return best_model
```

**Step 5: 테스트 실행**

```bash
python -m pytest tests/test_chat_handler_limits.py -v
python -m pytest tests/test_anthropic_handler.py -v
python -m pytest tests/ -v  # 전체 테스트
```

**Step 6: 커밋**

```bash
git add src/handlers/anthropic.py src/handlers/chat.py
git commit -m "feat: compaction 대신 CCR-style long-context 라우팅 도입"
```

---

## Task 3: 토큰 추정 정확도 개선

**Objective:** chars/4 방식의 부정확한 토큰 추정을 개선. 이미지/base64 데이터를 토큰 추정에서 제외하고, tool_result content는 실측 길이 기반으로 보정

**Files:**
- Modify: `src/handlers/chat.py:188-210` (_estimate_request_tokens)
- Test: `tests/test_chat_handler_limits.py`

**Step 1: 이미지 데이터 제외 로직 추가**

`_estimate_request_tokens`에서 image_url 블록의 base64 데이터는 실제 토큰화 시 다르게 처리되므로, 추정에서 이미지 데이터를 제외하고 placeholder 길이만 계산:

```python
@staticmethod
def _estimate_request_tokens(req: Dict[str, Any]) -> int:
    messages = req.get("messages", [])
    total_chars = 0

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    total_chars += len(str(block.get("text", "")))
                elif block.get("type") == "image_url":
                    # base64 이미지는 실제 토큰화 시 소수의 토큰만 사용되므로
                    # 과대추정 방지를 위해 작은 고정값 사용 (약 85토큰)
                    total_chars += 85 * 4  # 85 tokens → ~340 chars
                else:
                    # tool_result 등 기타 블록은 JSON 직렬화
                    total_chars += len(safe_json_dumps(block, ""))
        elif isinstance(content, dict):
            total_chars += len(safe_json_dumps(content, ""))

    # tools, tool_choice 등 추가 고려
    tools = req.get("tools")
    if isinstance(tools, list):
        total_chars += len(json.dumps(tools, ensure_ascii=False, default=str))

    return max(1, int(total_chars / 3.5))  # chars/3.5가 chars/4보다 더 정확
```

**Step 2: 테스트 실행**

```bash
python -m pytest tests/test_chat_handler_limits.py -v
```

**Step 3: 커밋**

```bash
git add src/handlers/chat.py
git commit -m "fix: 토큰 추정에서 이미지 base64 과대추정 방지"
```

---

## Task 4: 업스트림 context overflow 에러 발생 시 자동 fallback

**Objective:** CCR처럼 upstream에서 context overflow 에러 발생 시 다른 모델로 자동 재시도

**Files:**
- Modify: `src/handlers/chat.py` (handle_chat_request 에러 처리)
- Modify: `src/routes/anthropic.py` (messages 함수 에러 처리)
- Modify: `src/routes/openai.py` (chat_completions 함수 에러 처리)

**Step 1: `handle_chat_request`에서 context overflow 감지 및 재시도**

```python
def _handle_context_overflow_fallback(
    self, req: Dict[str, Any], error_msg: str
) -> Optional[requests.Response | Dict | ProxyRequestError]:
    """Context overflow 발생 시 long-context 모델로 자동 재시도"""
    if not ErrorHandler.is_context_overflow_message(error_msg):
        return None  # context overflow가 아니면 재시도 안 함

    requested_model = req.get("model", "")
    long_context_model = self._find_long_context_model(requested_model)
    if not long_context_model or long_context_model == requested_model:
        return None  # 재시도할 모델이 없음

    logging.warning(
        "[ContextOverflowFallback] %s → %s 재시도",
        requested_model, long_context_model
    )

    retry_req = dict(req)
    retry_req["model"] = long_context_model
    return self.handle_chat_request(retry_req)
```

**Step 2: 테스트 실행**

```bash
python -m pytest tests/ -v
```

**Step 3: 커밋**

```bash
git add src/handlers/chat.py src/routes/anthropic.py src/routes/openai.py
git commit -m "feat: context overflow 시 long-context 모델로 자동 fallback"
```

---

## Task 5: 통합 테스트 및 검증

**Objective:** 전체 변경 사항이 올바르게 작동하는지 통합 검증

**Step 1: 전체 테스트 실행**

```bash
cd /Users/jbj/Desktop/work/my/project/ollama-proxy
source .venv/bin/activate
python -m pytest tests/ -v
```

**Step 2: 빌드 검증 (해당하는 경우)**

```bash
# Flask 앱이므로 Python import 검증
python -c "from app import create_app; app = create_app(); print('OK')"
```

**Step 3: 기존 테스트 모두 통과 확인**

```bash
python -m pytest tests/ -v 2>&1 | tail -20
```

---

## 변경 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `src/handlers/anthropic.py` | `_tool_result_content_to_text` 단순화 (CCR처럼 stringify) |
| `src/handlers/anthropic.py` | `_skip_compaction: True` 제거 |
| `src/handlers/chat.py` | `_maybe_compact_request` → `_maybe_route_long_context`로 변경 |
| `src/handlers/chat.py` | `_find_long_context_model` 추가 |
| `src/handlers/chat.py` | `_estimate_request_tokens` 개선 (이미지 데이터 제외) |
| `src/handlers/chat.py` | `_handle_context_overflow_fallback` 추가 |
| `tests/test_anthropic_handler.py` | 변경된 tool_result 처리에 맞게 일부 테스트 갱신 |

## Risks & Tradeoffs

1. **tool_result content stringify**: 기존에는 text 블록만 추출했는데, 전체를 JSON.stringify하는 방식으로 변경하면 응답이 더 커질 수 있다. 하지만 CCR도 동일한 방식이므로 일관성을 위해 채택.
2. **Long-context 라우팅**: 같은 provider 내에서 더 큰 context_length 모델을 찾는 방식은 CCR의 명시적 설정 방식보다 불완전할 수 있음. 추후 config로 개선 필요.
3. **토큰 추정**: chars/3.5 방식은 여전히 근사치. 정확한 토큰 카운팅이 필요하면 tiktoken 의존성 추가 검토.
4. **Fallback 무한 루프**: `_handle_context_overflow_fallback`에서 동일 모델로 재시도하는 경우 방어 로직 포함됨.
