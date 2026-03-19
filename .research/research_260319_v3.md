## CLI Proxy API 환경변수 전달 누락 조사

### 요청 배경
- 사용자는 `cli-proxy-api` provider 호출 실패 원인 파악 후 즉시 수정까지 요청했다.
- `.env` 에 값을 추가했다고 했으므로, 민감 파일 자체는 읽지 않고 실행 중 컨테이너 상태와 compose 전달 경로를 기준으로 확인했다.

### 확인 결과
- 실행 중 컨테이너 `ollama-proxy` 내부에서 `CLI_PROXY_API_KEYS` 는 비어 있었고 `CLI_PROXY_API_BASE_URL` 도 설정되지 않았다.
- `ollama-proxy` 기동 로그에는 다음 사실이 명확히 남아 있었다.
  - `CLI_PROXY_API_KEYS 환경 변수가 설정되지 않았습니다.`
  - `[CLIProxyAPI] API 키 수: 0개`
- `docker-compose.yml` 의 `ollama-proxy.environment` 목록에는 다음 항목만 있었고 `CLI_PROXY_API_KEYS`, `CLI_PROXY_API_BASE_URL` 은 누락되어 있었다.
  - `GOOGLE_API_KEYS`
  - `OPENROUTER_API_KEYS`
  - `AKASH_API_KEYS`
  - `COHERE_API_KEYS`
  - `CODESTRAL_API_KEYS`
  - `ANTIGRAVITY_API_KEYS`
  - `PROXY_API_TOKEN`
  - `OLLAMA_API_KEYS`
  - `OLLAMA_BASE_URL`

### 네트워크 확인
- `docker inspect` 결과 `ollama-proxy` 는 `ollama-proxy_default`, `cli-proxy-api` 는 `cli-proxy-api_default` 와 `nginx-network` 에 연결되어 있었다.
- 즉 두 컨테이너는 기본적으로 서로 다른 Docker 네트워크에 있으므로, `ollama-proxy` 를 그대로 두면 서비스명 `cli-proxy-api` 가 해석되지 않는다.
- `host.docker.internal` 경로도 테스트했지만 이 환경에서는 `8317` 연결이 타임아웃이었다.
- 따라서 현재 구조에서 가장 안정적인 방법은 `ollama-proxy` 를 `nginx-network` 에도 함께 붙여서 `cli-proxy-api` 와 같은 네트워크에서 서비스명으로 통신하게 만드는 것이다.

### 결론
- 장애 1차 원인: `docker-compose.yml` 이 `.env` 값을 컨테이너로 전달하지 않음
- 장애 2차 원인: 기본 base URL 이 실제 Docker 네트워크 구조와 맞지 않음

### 최종 검증
- `ollama-proxy` 재기동 후 `CLI_PROXY_API_KEYS` 는 로드되었고, 시작 로그에 `[CLIProxyAPI] API 키 수: 1개` 가 찍혔다.
- `ollama-proxy` 컨테이너 안에서 `getent hosts cli-proxy-api` 가 `172.19.0.8` 로 해석되었다.
- `http://cli-proxy-api:8317/v1/models` 직접 호출은 `401 {"error":"Missing API key"}` 를 반환했다.
- 이 응답은 네트워크 연결과 HTTP 라우팅은 정상이며, 인증 없는 직접 접근만 거부되고 있음을 의미한다.

### 수정 방향
1. `docker-compose.yml` 의 `ollama-proxy.environment` 에 `CLI_PROXY_API_KEYS`, `CLI_PROXY_API_BASE_URL` 추가
2. `docker-compose.yml` 에 `nginx-network` 외부 네트워크 연결 추가
3. 코드 기본값을 `http://cli-proxy-api:8317/v1` 로 유지하되, 같은 네트워크에서 이름 해석 가능하게 구성
4. README 예시도 동일하게 수정
