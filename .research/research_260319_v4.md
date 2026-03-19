## Compact 모델 전환 조사

### 요청 배경
- 사용자는 compact 처리에 사용하는 내부 모델을 `cli-proxy-api` 의 Gemini 3 Pro로 변경해 달라고 요청했다.

### 현재 구현 상태
- compact 모델 상수는 `src/handlers/chat.py` 에서 `COMPACTION_MODEL = "antigravity:anti-gemini-3.1-pro-high"` 로 정의되어 있었다.
- compact 요청은 `_build_compaction_request()` 에서 생성되고, 최종적으로 `handle_chat_request()` 를 재호출하여 provider prefix 기반 라우팅을 탄다.
- provider 파싱 로직은 `_parse_model()` 에서 `provider:model` 형식을 분리하며, `cli-proxy-api:gemini-3-pro-preview` 라면:
  - provider: `cli-proxy-api`
  - upstream payload model: `gemini-3-pro-preview`
  로 전달된다.

### 모델 메타데이터 확인
- `models.json` 에 `cli-proxy-api:gemini-3-pro-preview` 모델이 이미 등록되어 있다.
- 현재 해당 모델은 `context_length: 1000000` 만 명시되어 있고 `max_output_tokens` 는 없다.
- 현 구현상 `max_output_tokens` 가 없으면 compact 요청의 출력 토큰 상한은 기본값 `32000` 을 사용한다.

### 수정 방향
1. `COMPACTION_MODEL` 을 `cli-proxy-api:gemini-3-pro-preview` 로 변경
2. compact 테스트가 `antigravity_client` 대신 `cli_proxy_api_client` 를 검증하도록 수정
3. payload model 검증은 provider prefix 가 제거된 `gemini-3-pro-preview` 기준으로 맞춤
