class ErrorHandler:
    @staticmethod
    def handle_api_error(provider: str, error: Exception, api_key: str = ""):
        """
        API 오류를 표준화된 형식으로 처리하고 로깅합니다.
        :param provider: API 제공업체 이름 (Google, OpenRouter 등)
        :param error: 발생한 예외 객체
        :param api_key: 사용된 API 키 (마스킹 처리)
        """
        masked_key = f"{api_key[:6]}...{api_key[-4:]}" if api_key else "None"
        return f"[{provider} API Error] Key: {masked_key} - {str(error)}"

    @staticmethod
    def create_error_response(model: str, error_msg: str):
        """
        오류 응답 생성 (Ollama 형식)
        :param model: 요청 모델 이름
        :param error_msg: 오류 메시지
        :return: 오류 응답 딕셔너리
        """
        return {
            "model": model,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "message": {"role": "assistant", "content": f"오류 발생: {error_msg}"},
            "done": True,
            "error": error_msg
        }
