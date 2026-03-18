# 2026-03-18 오류 분석: `messages.4.content.0.text.text: Field required`

## 요약

- 사용자에게 보인 400 오류는 `ollama-proxy`의 직접 검증 오류가 아니라, 상위 `antigravity-proxy`가 `anti-claude-opus-4-6-thinking` 백엔드로 요청을 보낼 때 받은 업스트림 검증 오류입니다.
- 오류는 2026-03-18 15:58:02, 15:59:05(KST)에 재현되었습니다.
- 공통 패턴:
  - 모델: `anti-claude-opus-4-6-thinking`
  - 도구 사용 활성화: `tools=30`
  - 누적 대화 히스토리 포함: `msgs=8`, `msgs=10`
  - 업스트림 오류: `messages.4.content.0.text.text: Field required`

## 확인한 로그

### ollama-proxy 컨테이너

- `Anthropic /v1/messages` 요청 자체는 정상 수신됨.
- 실패 직전 요청도 `ollama-proxy`에서는 `provider=Antigravity`로 전달됨.
- `ollama-proxy` 컨테이너 로그에는 직접적인 400 스택이 남지 않음.

### antigravity-proxy 컨테이너

실패가 실제로 기록된 위치:

- `2026-03-18 15:58:00,714`  
  `[Antigravity] 🔧 페이로드 | anti-claude-opus-4-6-thinking→claude-opus-4-6-thinking thinking=off tools=✓ msgs=8`
- `2026-03-18 15:58:02,352`  
  `[Antigravity] ❌ 요청 오류(400): ... "messages.4.content.0.text.text: Field required" ...`

- `2026-03-18 15:59:04,693`  
  `[Antigravity] 🔧 페이로드 | anti-claude-opus-4-6-thinking→claude-opus-4-6-thinking thinking=off tools=✓ msgs=10`
- `2026-03-18 15:59:05,703`  
  `[Antigravity] ❌ 요청 오류(400): ... "messages.4.content.0.text.text: Field required" ...`

즉, 동일한 대화가 누적되면서 5번째 메시지(`messages[4]`)의 첫 번째 content block이 Claude/Vertex 측 스키마를 만족하지 못하고 있습니다.

## 코드 기준 원인 후보

### 1. 실제 실패 위치

`antigravity-proxy/client.py`

- `_build_payload()`가 Claude 계열 모델 요청을 만들고
- `_build_contents()` / `_extract_content_parts()`가 OpenAI 메시지를 백엔드용 `contents`로 바꿉니다.

문제 가능성이 가장 높은 부분:

```python
def _extract_content_parts(content) -> list:
    if isinstance(content, list):
        parts = []
        for part in content:
            if part.get("type") == "text":
                parts.append({"text": part.get("text", "")})
```

여기서는 `part["text"]`가 문자열인지 검증하지 않습니다.  
만약 어떤 메시지 블록이 다음과 비슷한 형태로 들어오면:

```json
{"type":"text","text":{"...":"..."}}
```

그대로 `{"text": {...}}`가 업스트림으로 전달될 수 있고, Claude/Vertex 변환 단계에서
`messages.4.content.0.text.text` 같은 검증 오류가 발생할 수 있습니다.

### 2. 왜 tool 사용 이후에만 보이는가

실패한 요청은 모두 `tools=30`이며, 첫 요청(`msgs=2`, `msgs=4`)은 통과하고 그 다음 누적 요청(`msgs=8`, `msgs=10`)에서 깨졌습니다.

즉, 초기 사용자 메시지보다 다음 중 하나가 5번째 메시지로 누적되면서 잘못된 구조가 들어간 것으로 보는 게 맞습니다.

- 이전 assistant 응답의 text block
- tool result 이후 재구성된 user/tool 메시지
- content가 배열인 message의 재직렬화 결과

## ollama-proxy 쪽에서 확인한 관련 흐름

`src/handlers/anthropic.py`

- `_normalize_messages()`는 Anthropic 요청을 OpenAI 스타일 메시지로 변환합니다.
- `tool_result`는 최종적으로 `role="tool"` + 문자열 `content`로 변환됩니다.

따라서 현재 확인 가능한 범위에서는 **최종 스키마 파손은 `ollama-proxy`보다 `antigravity-proxy`의 Claude 요청 재구성 단계에서 발생할 가능성이 더 높습니다.**

## 결론

현재 로그 기준 직접 원인은 다음과 같습니다.

1. `ollama-proxy`가 `antigravity:anti-claude-opus-4-6-thinking` 요청을 전달함
2. `antigravity-proxy`가 이를 `claude-opus-4-6-thinking` 업스트림 요청으로 변환함
3. 누적 대화의 5번째 메시지(`messages[4]`) 첫 text block이 Claude/Vertex 스키마를 만족하지 못함
4. 업스트림이 `messages.4.content.0.text.text: Field required`로 400 반환

즉, **원인은 "Claude 업스트림에 전달된 5번째 메시지의 text block 구조가 잘못되었기 때문"이며, 가장 의심되는 변환 지점은 `antigravity-proxy/client.py`의 `_extract_content_parts()` 및 그 주변 메시지 재구성 로직**입니다.

## 다음 확인 포인트

재현 시 정확한 입력을 고정하려면 아래 로그가 추가로 필요합니다.

- `antigravity-proxy`에서 `_build_payload()` 직전 `messages[4]` 원본 dump
- `_extract_content_parts()` 진입 시 `content` 타입/샘플
- Claude 모델일 때 최종 `request.contents` 또는 변환 직전 block 샘플

이 3가지를 찍으면 어떤 블록이 `text` 문자열 대신 객체로 들어오는지 바로 특정할 수 있습니다.
