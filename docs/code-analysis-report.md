# Ollama Proxy 코드 분석 보고서

> **작성일**: 2026-06-09  
> **분석 범위**: 전체 소스 코드 30개+ 파일  
> **발견 이슈**: 총 73건 (Critical 11 / High 21 / Medium 28 / Low 13)

---

## 목차

1. [Critical — 즉시 수정 필요](#1-critical--즉시-수정-필요)
2. [High — 빠른 수정 필요](#2-high--빠른-수정-필요)
3. [Medium — 개선 필요](#3-medium--개선-필요)
4. [Low — 개선 검토](#4-low--개선-검토)
5. [구조적 리팩토링 권장사항](#5-구조적-리팩토링-권장사항)
6. [우선 수정 권장 순서](#6-우선-수정-권장-순서)

---

## 1. Critical — 즉시 수정 필요

### C1. KeyRotator `key_health`가 멀티 프로세스 간 공유되지 않음

- **파일**: `src/auth/key_rotator.py` L144
- **문제**: 파일 기반 인덱스로 멀티 프로세스 동기화를 시도하지만, `key_health` 딕셔너리는 각 프로세스의 메모리에만 존재함
- **영향**: gunicorn 등 멀티 프로세스 환경에서 프로세스 A가 기록한 Rate Limit 정보가 프로세스 B에 전파되지 않아, Rate Limited된 키를 다른 프로세스가 계속 사용
- **개선**: Redis, 공유 메모리, 또는 파일 기반 상태 저장소 사용

### C2. KeyRotator 스레드 안전성 미보장

- **파일**: `src/auth/key_rotator.py`
- **문제**: `_keys` 리스트와 `_index`에 대한 잠금(Lock)이 불완전하며, `get_available_key_count()` 등 일부 메서드가 Lock 없이 `key_health` 접근
- **영향**: 같은 키를 동시에 선택하거나, 인덱스 범위 초과로 `IndexError` 발생

### C3. QwenOAuthManager 토큰 갱신 경쟁 조건

- **파일**: `src/auth/qwen_oauth.py` L70-115
- **문제**: 토큰 만료 확인 → 갱신 사이에 여러 스레드가 동시 갱신 시도 가능. `is_token_valid()`도 Lock 없이 인스턴스 변수 접근
- **개선**: 갱신 로직에 `threading.Lock` 적용

### C4. `_build_provider()`에서 `None` 반환 → AttributeError

- **파일**: `src/handlers/chat.py` L90-140
- **문제**: 매칭되지 않는 `provider_type` 시 `None` 반환, 이후 `None.make_request()` 호출로 크래시
- **개선**: `None` 대신 `ValueError` 예외 발생

### C5. 스트리밍 응답 중 연결 끊김 미처리

- **파일**: `src/handlers/chat.py` L280-350
- **문제**: upstream `ChunkedEncodingError`/`ConnectionError` 미처리, 클라이언트 `GeneratorExit` 정리 불완전
- **영향**: 연결 끊김 시 리소스 누수 또는 미처리 예외 발생

### C6. anthropic.py 62KB — 과도한 책임 집중

- **파일**: `src/handlers/anthropic.py`
- **문제**: 요청 변환, 응답 변환, 스트리밍, 에러 처리, 메시지 정규화가 단일 파일에 집중. `_convert_messages()` 메서드 내 5-6단계 깊은 중첩으로 유지보수 곤란

### C7. tool_use/tool_result 변환 시 데이터 손실

- **파일**: `src/handlers/anthropic.py` L500-600
- **문제**: OpenAI ↔ Anthropic 형식 변환 시 지원하지 않는 필드 누락, `arguments`가 문자열이 아닌 경우 에러 발생

### C8. opencode_anthropic.py 18KB — 유틸에 비즈니스 로직 집중

- **파일**: `src/utils/opencode_anthropic.py`
- **문제**: 변환 로직이 유틸 파일에 있으나, 실제로는 핸들러 수준의 비즈니스 로직. 별도 변환 모듈이나 핸들러 하위 모듈로 이동 필요

### C9. check_ollama_keys.py 하드코딩된 경로

- **파일**: `check_ollama_keys.py` L7
- **문제**: `'/home/jjb/Desktop/work/my/project/ollama-proxy/.env'` 하드코딩. 현재 macOS 환경(`/Users/jbj/`)에서 `FileNotFoundError` 발생
- **개선**: `os.path.join(os.path.dirname(__file__), '.env')` 사용

### C10. GoogleApiClient가 BaseApiClient 미상속

- **파일**: `src/providers/google.py` L29
- **문제**: 공통 에러 처리 로직(컨텍스트 초과 검사, non-retryable 400 에러, 업스트림 프록시 에러, Rate Limit 키 비활성화 등)이 전혀 적용되지 않음. `providers/__init__.py`의 `__all__`에도 미포함
- **개선**: `BaseApiClient` 상속 또는 최소한 동일 에러 처리 적용

### C11. logging.py 모듈 임포트 시 자동 실행

- **파일**: `src/core/logging.py` L43
- **문제**: `logger = setup_logging()`이 모듈 레벨에서 실행되어, import만으로 앱 전체의 로깅 설정이 덮어씌워짐. 테스트나 다른 앱에서 import하면 의도치 않은 설정 변경 발생
- **개선**: 모듈 레벨 자동 실행 제거, 앱 진입점에서 명시적 호출로 변경

---

## 2. High — 빠른 수정 필요

### H1. `/tmp` 경로 하드코딩 — 보안 및 충돌 위험

- **파일**: `src/auth/key_rotator.py` L198-199
- **문제**: `/tmp/key_rotator_{provider}.lock` 및 `.index` 파일이 하드코딩. 심볼릭 링크 공격 취약, 여러 인스턴스 충돌 가능
- **개선**: `tempfile.mkdtemp()` 또는 설정 가능한 디렉토리 경로 사용

### H2. `fcntl` 플랫폼 의존성

- **파일**: `src/auth/key_rotator.py` L12
- **문제**: `fcntl`은 Unix 전용 모듈. Windows에서 `ModuleNotFoundError` 발생
- **개선**: 플랫폼별 분기 처리 또는 `filelock` 크로스 플랫폼 라이브러리 사용

### H3. FileLock.__exit__에서 None 접근

- **파일**: `src/auth/key_rotator.py` L107-109
- **문제**: `__enter__`에서 `open()` 호출 시 예외 발생하면 `self.file`이 `None`인 채로 `__exit__` 호출. `self.file.fileno()`에서 `AttributeError` 발생
- **개선**: `__exit__`에서 `self.file is not None` 확인 추가

### H4. OAuth 토큰 갱신 실패 후 만료 토큰 사용

- **파일**: `src/auth/qwen_oauth.py` L117-140
- **문제**: 네트워크 오류로 `_refresh_token()` 실패 시 로그만 찍고 기존 만료 토큰 유지. 만료된 토큰으로 API 호출 계속
- **개선**: 갱신 실패 시 명시적 에러 반환 또는 재시도 로직 추가

### H5. 자격 증명 파일 권한 미설정

- **파일**: `src/auth/qwen_oauth.py` L67
- **문제**: `_save_credentials`에서 파일 생성 시 기본 umask로 생성. 다른 사용자가 OAuth 토큰 읽기 가능
- **개선**: 파일 생성 후 `os.chmod(path, 0o600)` 설정

### H6. ThoughtTagFilter 상태 공유 문제 (동시성)

- **파일**: `src/handlers/response.py` L35, L307
- **문제**: `ThoughtTagFilter`가 인스턴스 변수로 유지되면서, 여러 요청이 동시에 같은 `ResponseHandler` 인스턴스를 사용하면 한 요청의 `reset()`이 다른 요청의 필터 상태를 초기화 — Race Condition
- **개선**: 각 스트리밍 호출마다 새 `ThoughtTagFilter` 인스턴스 생성

### H7. cursor 모드 헤더 반전 가능

- **파일**: `src/handlers/chat.py` L848
- **문제**: `cursor_has_tools`가 True이면 `"ask"`, False이면 `"agent"` 모드를 설정. 일반적으로 도구가 있으면 `"agent"`, 없으면 `"ask"`가 맞을 것 같은데 반대. 의도적이라면 주석 필요
- **개선**: 비즈니스 로직 확인 후 수정 또는 명확한 주석 추가

### H8. handle_non_streaming_response 예외 미처리

- **파일**: `src/handlers/anthropic.py` L902-904
- **문제**: `resp`가 `Response`일 때 `resp.json()`이 `JSONDecodeError`를 발생시킬 수 있지만, `try-except` 없음
- **개선**: `try-except`로 감싸서 적절한 에러 응답 반환

### H9. thought_filter 청크 경계에서 태그 분리 시 필터 실패

- **파일**: `src/utils/thought_filter.py` L38-55
- **문제**: 스트리밍 응답에서 `<thought>` 태그가 두 청크에 걸쳐 나뉠 수 있음 (예: `<thou` + `ght>내용</thought>`). 현재 한 번의 `filter()` 호출 내에서만 태그 매칭
- **개선**: 버퍼링 메커니즘 추가. `<` 문자 발견 시 잠재적 태그 시작으로 간주하고 충분한 문자가 모일 때까지 버퍼링

### H10. Google Data URL 파싱 IndexError

- **파일**: `src/providers/google.py` L142-143
- **문제**: `url.split(",")[1]`에서 `,`가 없는 잘못된 Data URL 입력 시 `IndexError` 발생
- **개선**: 분리 후 길이 확인 또는 try/except 추가

```python
# 현재 코드 (위험)
b64_data = url.split(",")[1]

# 개선
parts = url.split(",", 1)
if len(parts) < 2:
    continue
b64_data = parts[1]
```

### H11. Google HTTP 에러 세분화 부재

- **파일**: `src/providers/google.py` L424-446
- **문제**: `_make_request`에서 `resp.raise_for_status()` 호출 시 429(Rate Limit), 401(인증 실패) 등 모든 HTTP 에러를 동일하게 처리. Rate Limit 시 키 비활성화 로직 없음
- **개선**: `BaseApiClient.post_request()`처럼 상태 코드별 분기 처리

### H12. Google `candidates` 빈 배열

- **파일**: `src/providers/google.py` L150-200
- **문제**: Google API가 안전 필터로 응답을 차단한 경우 `candidates`가 빈 배열이거나 아예 없을 수 있음. `candidates[0]` 접근에서 `IndexError` 발생
- **개선**: 빈 배열/누락 시 방어 코드 추가

### H13. 복수 system 메시지 시 앞 메시지 무시

- **파일**: `src/providers/google.py` L200-260
- **문제**: `system` role 메시지를 `system_instruction`으로 변환하는데, 여러 `system` 메시지가 있을 때 마지막만 사용. 앞의 system 메시지 내용이 무시됨
- **개선**: 복수 system 메시지를 연결(concat)하여 사용

### H14. Qwen 토큰 `None` 전파

- **파일**: `src/providers/qwen.py` L30-60
- **문제**: `qwen_oauth_manager.get_next_token()`이 `None` 반환 시, `Authorization: Bearer None`으로 잘못된 요청 전송
- **개선**: `None` 체크 후 적절한 에러 응답 반환

### H15. HTTP 타임아웃 미설정

- **파일**: `src/providers/base.py` L80-130
- **문제**: `requests.post()` 호출에서 일부 경로에 타임아웃 없음. 네트워크 장애 시 무한 대기 가능
- **개선**: 일관된 타임아웃 설정 (connect=10s, read=120s 등)

### H16. 스트림 Response 리소스 해제 미보장

- **파일**: `src/providers/base.py` L130-180
- **문제**: `stream=True`로 요청한 `Response` 객체의 `close()`가 모든 예외 경로에서 호출되지 않음. Generator 타입의 `resp`도 마찬가지
- **개선**: `finally` 블록에서 Response/Generator 모두 `close()` 보장

### H17. 동일 환경변수 공유하는 두 rotator

- **파일**: `config.py` L57-62
- **문제**: `cli_proxy_api_rotator`와 `cli_proxy_api_plus_rotator` 모두 `"CLI_PROXY_API_KEYS"` 환경변수 사용. 동일 키 풀을 독립 순환하므로 같은 키 동시 사용 → rate limit 충돌
- **개선**: Plus용 별도 환경변수(`CLI_PROXY_API_PLUS_KEYS`) 사용 또는 의도적이라면 주석 명시

### H18. check_ollama_keys.py .env 파서 취약

- **파일**: `check_ollama_keys.py` L10-21
- **문제**: 직접 구현한 .env 파서가 따옴표/이스케이프/주석 처리 미흡. 파일 열기 예외 처리도 부재
- **개선**: `python-dotenv` 라이브러리 사용

### H19. `max_output_tokens` 폴백이 context_length

- **파일**: `src/utils/model_limits.py` L58
- **문제**: `max_output_tokens`가 없으면 `context_length` 값을 대신 사용. context_length(예: 200,000)가 output 한도로 사용되어 실제 모델 한도를 크게 초과
- **개선**: 합리적인 기본값(예: 8192) 사용 또는 `None` 반환

### H20. `is_available` 프로퍼티에서 상태 변경 (Side-effect)

- **파일**: `src/auth/key_rotator.py` L52-62
- **문제**: `is_available` 프로퍼티 접근 시 `is_rate_limited`, `rate_limit_until` 상태를 변경. 프로퍼티는 읽기만 하는 것으로 기대됨. Lock 없이 발생하면 스레드 안전하지 않음
- **개선**: 상태 변경 로직을 별도의 `check_and_reset_rate_limit()` 메서드로 분리

### H21. 원본 headers 딕셔너리 직접 변경

- **파일**: `src/providers/base.py` L134
- **문제**: `headers['Authorization'] = f'Bearer {api_key}'`에서 호출자가 전달한 `headers` 딕셔너리를 직접 수정. 호출자가 동일 headers 재사용 시 예기치 않은 키 노출
- **개선**: `headers = {**headers, 'Authorization': ...}` 또는 `headers.copy()` 사용

---

## 3. Medium — 개선 필요

### M1. `_hash_key` 초기화 불일치

- **파일**: `src/auth/key_rotator.py` L151 vs L225
- **문제**: 초기화 시 `key_hash=f"key_{i}"` 사용, 이후 `get_next_key`에서는 `key_hash=self._hash_key(...)` 사용. 같은 키에 대해 `key_hash` 값이 달라지는 비일관성

### M2. 로그에 API 키 과다 노출

- **파일**: `key_rotator.py`, `google.py`
- **문제**: key_rotator는 앞 6자+, google은 뒤 8자리를 로깅. 마스킹 정책 불일치
- **개선**: 일관된 마스킹 정책 적용 (앞 4자 + 뒤 4자 등)

### M3. QWEN_OAUTH_CREDENTIALS 파싱 예외 미처리

- **파일**: `src/auth/qwen_oauth.py` L30-48
- **문제**: `client_id:client_secret` 형식 외의 값 시 `ValueError` (언패킹 실패)로 앱 시작 크래시
- **개선**: try-except 추가

### M4. `get_access_token` 반환 타입 불일치

- **파일**: `src/auth/qwen_oauth.py` L73-81
- **문제**: 타입 힌트 `-> str`이지만 `_access_token`이 `None`일 수 있어 실제로는 `Optional[str]` 반환
- **개선**: 타입 힌트 수정 또는 None 시 빈 문자열 반환

### M5. OAuth 로그에 민감 정보 노출

- **파일**: `src/auth/qwen_oauth.py` L128
- **문제**: `response.text`를 그대로 로그 출력. OAuth 서버 응답에 토큰 정보 포함 가능
- **개선**: 응답 본문을 잘라내거나 특정 필드만 로깅

### M6. `datetime.utcnow()` Deprecated

- **파일**: `errors.py` L92, `ollama.py` L132, `response.py` L42
- **문제**: Python 3.12에서 deprecated
- **개선**: `datetime.now(timezone.utc)` 사용

### M7. 에러 응답에 API 키 정보 노출 가능

- **파일**: `src/core/errors.py`
- **문제**: upstream 에러 응답을 그대로 반환하면서, 응답 본문에 API 키 관련 정보 포함 가능. 필터링 없음

### M8. 디버그 로그 경로 하드코딩

- **파일**: `src/handlers/chat.py` L46-48, `src/handlers/anthropic.py` L31-33
- **문제**: `/Users/jbj/.cursor/debug-*.log` 개발자 로컬 경로 하드코딩. 다른 환경에서 경로 미존재
- **개선**: 환경변수 기반으로 변경하고, 공통 모듈로 추출

### M9. `_process_image_content` IndexError

- **파일**: `src/handlers/chat.py` L462-465
- **문제**: `content.split('data:image')` 결과가 1개 이하이면 `split1[1]`에서 IndexError. except로 잡지만 의도 불명확
- **개선**: 정규식 기반으로 변경, 실패 시 원본 보존 의도 문서화

### M10. `_maybe_compact_request` 반환 타입 불일치

- **파일**: `src/handlers/chat.py` L307, L335
- **문제**: 타입 힌트가 `Optional[Response | Dict | ProxyRequestError]`인데, L335에서 Generator 반환. Union 타입에 Generator 미포함
- **개선**: 반환 타입 힌트에 `Generator` 추가

### M11. `handle_chat_request` None 반환의 모호성

- **파일**: `src/handlers/chat.py` L758, L768
- **문제**: messages 없거나 provider 미발견 시 `None` 반환. 호출자가 `None` 처리에 따라 500 에러 가능
- **개선**: `ProxyRequestError` 반환

### M12. 응답 빌드 중복 코드

- **파일**: `src/handlers/anthropic.py`
- **문제**: Anthropic 형식 응답과 OpenAI 형식 응답 빌드 코드 사이 상당한 중복

### M13. 스트리밍 에러 후 최종 청크 미전송

- **파일**: `src/handlers/response.py` L401-415
- **문제**: 예외 발생 시 에러 청크를 yield하지만, 최종 `done` 청크가 yield되지 않아 클라이언트가 스트림 종료 미인식 가능

### M14. `response_closed` 변수 무의미

- **파일**: `src/handlers/response.py` L302, L417
- **문제**: `response_closed = False`로 초기화, `finally` 이후 다시 읽히지 않아 플래그 무용

### M15. User-Agent 헤더 미설정

- **파일**: `src/providers/base.py`
- **문제**: 프록시 요청에 User-Agent 미설정. 일부 제공업체 차단 가능

### M16. `print()` 사용 (프로덕션)

- **파일**: `src/providers/base.py` L269
- **문제**: `logging.error`와 함께 `print(error_msg)` 사용
- **개선**: `print` 제거, `logging`만 사용

### M17. Google `finishReason` 매핑 불완전

- **파일**: `src/providers/google.py` L300-340
- **문제**: `SAFETY`, `RECITATION` 등 Google 특유 종료 사유가 `stop`으로 일괄 변환. 클라이언트가 실제 중단 이유 파악 불가

### M18. 빈 메시지 배열 검증 부재

- **파일**: `src/routes/ollama.py` L40-80, `src/routes/openai.py` L100-108
- **문제**: `messages` 배열이 비거나 누락된 경우 검증 없음

### M19. `request.get_json(force=True)` None 반환 처리

- **파일**: `src/routes/ollama.py` L98
- **문제**: JSON 파싱 실패 시 `None` 반환. 이후 `req.get("model")`에서 `AttributeError`
- **개선**: `req`가 `None`인 경우 방어 코드 추가

### M20. 순환 import 가능성

- **파일**: `src/routes/openai.py` L31
- **문제**: `list_models()` 내에서 `from src.routes.ollama import get_tags` 지역 import
- **개선**: 공통 모델 로딩 로직을 별도 모듈로 분리

### M21. keys.py rotator 하드코딩

- **파일**: `src/routes/keys.py` L31-44
- **문제**: `api_config`의 rotator 속성들이 하드코딩. 새 제공업체 추가 시 코드 수정 필수. 일부 rotator가 `None`이면 `AttributeError`
- **개선**: `api_config`에 rotator 목록 반환 메서드 추가

### M22. quota 캐시 타입 힌트 불일치

- **파일**: `src/services/quota_service.py` L31, L52
- **문제**: `self._cache` 타입이 `Optional[Dict]`로 선언, 실제로 `List[AccountQuota]` 저장
- **개선**: `self._cache: Optional[List[AccountQuota]] = None`으로 수정

### M23. 전역 싱글톤 스레드 안전성 부재

- **파일**: `src/services/quota_service.py` L197-205
- **문제**: `get_quota_service()`에서 `global _quota_service`를 Lock 없이 읽기/쓰기
- **개선**: `threading.Lock()`으로 보호

### M24. `random.seed()` 전역 사이드 이펙트

- **파일**: `src/services/quota_service.py` L65
- **문제**: 전역 난수 생성기의 시드를 변경. 다른 모듈의 `random` 사용에 영향
- **개선**: `random.Random()` 인스턴스를 별도 생성

### M25. 스키마 재귀 깊이 제한 없음

- **파일**: `src/utils/schema_sanitizer.py` L30-80
- **문제**: 중첩된 JSON 스키마를 재귀 처리하는데, 악의적으로 깊은 중첩 시 `RecursionError`
- **개선**: 최대 깊이 파라미터 설정

### M26. `int()` 변환 예외 미처리

- **파일**: `src/utils/opencode_anthropic.py` L384, L427
- **문제**: `int(event.get("index", 0))`에서 `index` 값이 문자열이면 `ValueError`. SSE 스트림 전체 중단
- **개선**: try-except로 감싸기

### M27. 전역 캐시 스레드 안전성 부재

- **파일**: `src/utils/model_limits.py` L20, L73-81
- **문제**: `_MODEL_LIMITS_CACHE`를 Lock 없이 멀티스레드에서 읽기/쓰기. 동시 로드 시 경쟁 조건
- **개선**: 모듈 로드 시 즉시 로드 또는 `threading.Lock()` 사용

### M28. 프로바이더 초기화 실패 시 전체 앱 중단

- **파일**: `config.py` L19-79
- **문제**: 하나의 `KeyRotator` 초기화가 예외를 던지면 전체 앱 미시작. 특정 프로바이더 키가 없는 것은 일반적 상황
- **개선**: 각 rotator 초기화를 try-except로 감싸기

---

## 4. Low — 개선 검토

### L1. 에러 처리 함수 중복 패턴

- **파일**: `src/core/errors.py`
- **문제**: `extract_error_message`, `extract_error_code`, `extract_error_type`가 동일한 JSON 파싱 로직 반복
- **개선**: 공통 파싱 헬퍼 `_parse_error_body()` 추출

### L2. 주석에 한자 혼재

- **파일**: `src/auth/key_rotator.py` L255/281/305/312, `src/models/quota.py` L15/17
- **문제**: `最高的`, `之后再试`, `惩罚`, `单个模型`, `时间` 등 한자 사용. 프로젝트 한국어 규칙 위배
- **개선**: 한국어로 통일

### L3. 중복 import

- **파일**: `src/handlers/chat.py` L8-15
- **문제**: `import json`, `import os`, `import time` 각각 2회 중복

### L4. `_agent_debug_log` 함수 중복

- **파일**: `src/handlers/chat.py` L51-71, `src/handlers/anthropic.py` L37-57
- **문제**: 동일한 함수와 `_DEBUG_LOG_PATH` 변수가 두 파일에 완전히 중복 정의
- **개선**: 공통 유틸리티 모듈로 추출

### L5. `_sanitize_tool_id` 이중 변환

- **파일**: `src/handlers/anthropic.py` L199-206
- **문제**: `call_` → `toolu_` 변환을 두 번 수행. 첫 변환 후 sanitize를 거치면 이미 `toolu_`로 변환된 상태인데 다시 `call_` 체크
- **개선**: 두 번째 체크 제거

### L6. 미사용 import

- **파일**: `src/models/quota.py` L9-10 (`datetime`, `Dict`), `check_ollama_keys.py` L3 (`json`)

### L7. 함수 내부 import

- **파일**: `src/auth/key_rotator.py` L155 (`hashlib`), L307 (`random`), `src/utils/text_extraction.py` L75 (`json`)
- **개선**: 파일 상단으로 이동

### L8. `models.json` `name`과 `model` 값 동일

- **파일**: `models.json`
- **문제**: 모든 모델에서 `name`과 `model` 값이 동일한 중복 데이터
- **개선**: 하나로 통합하거나 코드에서 자동 복사

### L9. `models.json` `max_output_tokens` 누락

- **파일**: `models.json`
- **문제**: `codestral:codestral-2508`, `opencode:mimo-v2.5`, `opencode:minimax-m3`, `opencode:minimax-m2.5` 등 6개+ 모델에서 누락
- **영향**: H19(폴백이 context_length)와 연관

### L10. `sys.path` 직접 조작

- **파일**: `src/cli/__init__.py` L13
- **문제**: `sys.path.insert(0, ...)` 로 상위 디렉토리 직접 추가. 패키지 구조 오염 가능
- **개선**: `pyproject.toml`에 entry_points 정의

### L11. f-string 로깅

- **파일**: `src/handlers/response.py` 다수
- **문제**: `logging` 모듈에서 f-string 사용 시 로그 레벨 비활성이라도 포매팅 항상 실행
- **개선**: `logger.info("msg %s", var)` 형태로 전환

### L12. 변수명 재사용 혼동

- **파일**: `src/handlers/response.py` L521, L540
- **문제**: `message` 변수가 응답 메시지 → Ollama 메시지로 같은 이름 재정의
- **개선**: `ollama_message` 등으로 이름 구분

### L13. `flush_user_content` 클로저 side-effect

- **파일**: `src/handlers/anthropic.py` L449-472
- **문제**: 외부 변수 `pending_content_blocks`와 `normalized`를 직접 수정하는 클로저
- **개선**: 반환값 기반으로 리팩토링

---

## 5. 구조적 리팩토링 권장사항

### 5-1. 대형 파일 분리 (가장 높은 ROI)

```
src/handlers/anthropic.py (62KB) →
  ├── anthropic_request.py     (요청 변환, 메시지 정규화)
  ├── anthropic_response.py    (응답 변환, 형식 빌드)
  ├── anthropic_stream.py      (스트리밍 처리, 이벤트 파싱)
  └── anthropic_handler.py     (오케스트레이션)

src/utils/opencode_anthropic.py (18KB) →
  src/handlers/opencode/       또는
  src/converters/opencode_anthropic.py
```

### 5-2. 스레드/프로세스 안전성 확보

```python
# KeyRotator 적용 예시
class KeyRotator:
    def __init__(self, ...):
        self._lock = threading.Lock()

    def get_next_key(self):
        with self._lock:
            ...

    def get_available_key_count(self):
        with self._lock:       # 현재 Lock 없음
            ...
```

> **참고**: `key_health` 딕셔너리는 프로세스 간 공유 불가.
> gunicorn 멀티 프로세스 환경에서는 Redis 등 외부 상태 저장소가 필요.

### 5-3. 모델 정보 단일 소스 관리

```
models.json (유일한 모델 정의)
  ├── 모델명, 제공업체, 토큰 제한, 라우팅 정보 통합
  ├── chat.py의 _resolve_provider() → models.json 참조
  ├── model_limits.py → models.json에서 직접 로드
  └── max_output_tokens 누락 모델 보완
```

### 5-4. Google 프로바이더 정규화

```
GoogleApiClient → BaseApiClient 상속
  ├── 공통 에러 처리 (컨텍스트 초과, Rate Limit, 인증 실패)
  ├── Data URL 파싱 방어 코드
  ├── candidates 빈 배열 처리
  └── providers/__init__.py __all__에 추가
```

### 5-5. 에러 처리 체계화

- `except Exception` → 구체적 예외 타입으로 세분화
- upstream 응답의 API 키 정보 필터링
- 스트리밍 연결 끊김에 대한 통일된 정리 로직
- `finally` 블록에서 Response/Generator 모두 `close()` 보장

### 5-6. 공통 유틸 정리

```python
# 현재: chat.py와 anthropic.py에 동일 함수 중복
# 개선:
src/utils/debug_log.py
    def agent_debug_log(...)  # 하드코딩 경로 → 환경변수 기반
```

---

## 6. 우선 수정 권장 순서

> 프로덕션 안정성 영향도 기준 정렬

### Phase 1: 런타임 크래시 방지 (즉시)

1. **C4**: `_build_provider()` None → ValueError 변경
2. **C9**: check_ollama_keys.py 하드코딩 경로 수정
3. **H10**: Google Data URL 파싱 IndexError 방어
4. **H12**: Google candidates 빈 배열 처리
5. **M19**: `request.get_json()` None 반환 처리

### Phase 2: 동시성/안전성 (1주 내)

6. **C1/C2**: KeyRotator 스레드 안전성 + 프로세스 간 상태 공유
7. **C3**: QwenOAuthManager Lock 추가
8. **H6**: ThoughtTagFilter 인스턴스 분리
9. **H20**: `is_available` 프로퍼티 side-effect 분리
10. **H21**: headers 딕셔너리 복사

### Phase 3: 에러 처리 보강 (2주 내)

11. **C10**: GoogleApiClient → BaseApiClient 상속
12. **H11**: Google HTTP 에러 세분화
13. **H8**: anthropic handle_non_streaming JSONDecodeError 처리
14. **C5**: 스트리밍 연결 끊김 정리
15. **H15/H16**: HTTP 타임아웃 및 Response 리소스 해제

### Phase 4: 구조적 리팩토링 (1개월 내)

16. **C6**: anthropic.py 파일 분리
17. **C8**: opencode_anthropic.py 위치 이동
18. **H17**: CLI_PROXY_API_KEYS 환경변수 분리
19. 모델 정보 단일 소스 관리
20. 나머지 Medium/Low 이슈들
