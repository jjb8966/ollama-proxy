## 모델별 context, max token 공식 문서 재검증

### 조사 기준
- 사용자 요청에 따라 각 모델의 공식 사이트 또는 공식 API 문서만 사용했다.
- provider 별칭 모델은 실제 원모델의 공식 문서 또는 해당 provider의 공식 모델 문서를 기준으로 매핑했다.
- 공식 문서에 `max output tokens` 가 명시되지 않은 경우에는 값을 억지로 추정하지 않고 비워 두는 방향을 택했다.

### 주요 확인 결과

#### Anthropic 계열
- 공식 문서: Claude Models Overview
- 확인 결과
  - `claude-opus-4-6`: context 200K, max output 128K
  - `claude-sonnet-4-6`: context 200K, max output 64K
- 영향 범위
  - `antigravity:anti-claude-opus-4-6-thinking`
  - `antigravity:anti-claude-sonnet-4-6`
  - `antigravity:claude-opus-4-6-thinking`
  - `antigravity:claude-sonnet-4-6`

#### Gemini 계열
- 공식 문서: Google Gemini API model pages
- 확인 결과
  - `gemini-3.1-pro-preview`: input 1,048,576 / output 65,536
  - `gemini-3.1-pro-preview-customtools`: input 1,048,576 / output 65,536
  - `gemini-3-flash-preview`: input 1,048,576 / output 65,536
  - `gemini-3.1-flash-lite-preview`: input 1,048,576 / output 65,536
  - `gemini-3-pro-preview`: input 1,048,576 / output 65,536
- 주의 사항
  - Google 공식 문서상 `gemini-3-pro-preview` 는 2026-03-09 에 shut down 되었고 `gemini-3.1-pro-preview` 로 마이그레이션 안내가 있다.
- 영향 범위
  - `google:*`
  - `cli-proxy-api:gemini-3-*`
  - `antigravity:gemini-*`
  - `antigravity:anti-gemini-*`
  - `antigravity:gcli-gemini-*`

#### OpenAI 계열
- 공식 문서: OpenAI model pages
- 확인 결과
  - `gpt-5.2`: context 400,000 / max output 128,000
  - `gpt-5.2-codex`: context 400,000 / max output 128,000
- 영향 범위
  - `cli-proxy-api:gpt-5.2`
  - `cli-proxy-api:gpt-5.2-codex`

#### Cohere 계열
- 공식 문서: Cohere model docs
- 확인 결과
  - `command-a-03-2025`: context 256,000 / max output 8,000
  - `command-a-reasoning-08-2025`: context 256,000 / max output 32,000
- 영향 범위
  - `cohere:command-a-03-2025`
  - `cohere:command-a-reasoning-08-2025`

#### Mistral 계열
- 공식 문서: Mistral Docs
- 확인 결과
  - `codestral-2508`: context 128k
  - `mistral-large-2512`: context 256k
  - `devstral-2512`: context 256k
- 주의 사항
  - Codestral / Devstral / Mistral Large 문서에서는 본 프로젝트가 사용하는 방식의 엄격한 `max output tokens` 값을 찾지 못했다.
  - 기존 `max_output_tokens = context_length` 는 공식 문서 기반 값으로 보기 어려워 제거 대상이다.
- 영향 범위
  - `codestral:codestral-2508`
  - `nvidia-nim:mistralai/mistral-large-3-675b-instruct-2512`
  - `openrouter:mistralai/devstral-2512:free`

#### NVIDIA NIM 계열
- 공식 문서: NVIDIA API Catalog model pages
- 확인 결과
  - `minimaxai/minimax-m2.5`: context 204,800
  - `moonshotai/kimi-k2.5`: context 256,000
  - `mistralai/mistral-large-3-675b-instruct-2512`: context 262,144
  - `nvidia/nemotron-3-super-120b-a12b`: context up to 1,000,000
  - `openai/gpt-oss-120b`: context 128,000
  - `qwen/qwen3.5-397b-a17b`: input 262,144, output up to 81,920
  - `z-ai/glm4.7`: input 131,072, output 131,072
  - `z-ai/glm5`: maximum context length 205K
- 주의 사항
  - `qwen3.5-397b-a17b` 는 공식 문서가 `recommended 32,768`, `up to 81,920` 이라고 명시한다. 상한으로는 81,920 을 저장하는 것이 가장 근접하다.
  - `glm5` 는 NVIDIA 문서에서 context 205K, Z.AI 문서에서는 context 200K / max output 128K 로 보여 차이가 있다. `nvidia-nim:*` 행은 provider 실제 경로 기준으로 NVIDIA 값을 우선한다.

#### OpenRouter 계열
- 공식 문서: OpenRouter model pages
- 확인 결과
  - `kwaipilot/kat-coder-pro:free`: context 256,000
  - `mistralai/devstral-2512:free`: context 262,144
- 주의 사항
  - OpenRouter 페이지에서는 엄격한 `max output tokens` 값을 찾지 못했다.

#### Ollama Cloud 계열
- 공식 문서: Ollama model library / cloud docs
- 확인 결과
  - `kimi-k2.5:cloud`: context 256K
  - `minimax-m2.5:cloud`: context 198K
  - `glm-5:cloud`: context 198K
- 주의 사항
  - Ollama Cloud는 cloud 모델을 최대 context로 설정한다고 문서화한다.
  - `glm-5:cloud` 문서에는 평가용 `max_new_tokens=131072` 예시가 있으나, API 상 엄격한 출력 상한으로 명시된 것은 아니므로 `max_output_tokens` 는 보수적으로 비워 두는 편이 안전하다.

### 수정 원칙
1. 공식 문서에 명시된 context는 그대로 반영
2. 공식 문서에 명시된 max output은 그대로 반영
3. 공식 문서에 없는 max output은 삭제 또는 미기재 유지
4. provider 별칭은 원모델 문서 값을 상속

### 소스
- Anthropic: https://platform.claude.com/docs/en/about-claude/models/overview
- Google Gemini 3.1 Pro: https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview
- Google Gemini 3 Flash: https://ai.google.dev/gemini-api/docs/models/gemini-3-flash-preview
- Google Gemini 3.1 Flash-Lite: https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite-preview
- Google all models: https://ai.google.dev/gemini-api/docs/models
- OpenAI GPT-5.2: https://developers.openai.com/api/docs/models/gpt-5.2
- OpenAI GPT-5.2-Codex: https://developers.openai.com/api/docs/models/gpt-5.2-codex
- Cohere Command A: https://docs.cohere.com/docs/command-a
- Cohere Command A Reasoning: https://docs.cohere.com/docs/command-a-reasoning
- Mistral Codestral: https://docs.mistral.ai/models/codestral-25-08
- Mistral Devstral 2: https://docs.mistral.ai/models/devstral-2-25-12
- Mistral Large 3: https://docs.mistral.ai/models/mistral-large-3-25-12
- NVIDIA MiniMax M2.5: https://docs.api.nvidia.com/nim/reference/minimaxai-minimax-m2.5
- NVIDIA Kimi K2.5: https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k2-5
- NVIDIA Mistral Large 3 675B: https://docs.api.nvidia.com/nim/reference/mistralai-mistral-large-3-675b-instruct-2512
- NVIDIA Nemotron 3 Super: https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-super-120b-a12b
- NVIDIA GPT-OSS 120B: https://docs.api.nvidia.com/nim/reference/openai-gpt-oss-120b
- NVIDIA Qwen3.5 397B A17B: https://docs.api.nvidia.com/nim/reference/qwen-qwen3-5-397b-a17b
- NVIDIA GLM-4.7: https://docs.api.nvidia.com/nim/reference/z-ai-glm4-7
- NVIDIA GLM-5: https://docs.api.nvidia.com/nim/reference/z-ai-glm5
- OpenRouter KAT Coder Pro: https://openrouter.ai/kwaipilot/kat-coder-pro
- OpenRouter Devstral 2512: https://openrouter.ai/mistralai/devstral-2512%3Afree
- Ollama Kimi K2.5: https://ollama.com/library/kimi-k2.5
- Ollama MiniMax M2.5: https://ollama.com/library/minimax-m2.5
- Ollama GLM-5: https://ollama.com/library/glm-5
- Ollama cloud docs: https://docs.ollama.com/cloud
