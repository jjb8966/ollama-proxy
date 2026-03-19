## max token 처리 제거 및 사용자 직접 compact 전환

### 요청 배경
- 리뷰 결과 `max_tokens` 로컬 검증이 공식 메타데이터 정리와 충돌한다는 지적이 있었다.
- 사용자는 이에 대해:
  1. `max token 처리 로직은 그냥 빼`
  2. `사용자가 직접 compact 할거야`
  라고 명시했다.

### 변경 방향
1. `src/handlers/chat.py` 의 `_validate_max_tokens()` 제거
2. `handle_chat_request()` 에서 `max_tokens` 로컬 에러 반환 제거
3. 요청의 `max_tokens` 값은 그대로 upstream payload 에 전달
4. compact 안내 메시지는 내부 compact 수행이 아니라, 사용자가 직접 compact 후 다시 시도하라는 의미로 정리
5. `tests/test_chat_handler_limits.py` 에서 max token 에러 검증 테스트 제거

### 영향
- 프록시는 더 이상 `max_tokens` 를 자체 차단하지 않는다.
- 실제 상한 검증은 upstream provider 가 수행한다.
- context 임계값 초과는 계속 안내 메시지로 응답한다.
