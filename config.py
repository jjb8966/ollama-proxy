# -*- coding: utf-8 -*-
"""
API 설정 모듈

각 LLM 제공업체의 API 키 순환기를 초기화합니다.
"""

from src.auth.key_rotator import KeyRotator


class ApiConfig:
    """
    API 설정 및 인증 관리 클래스

    각 제공업체별 KeyRotator를 초기화하고 관리합니다.
    """

    def __init__(self):
        self.antigravity_rotator = KeyRotator("Antigravity", "ANTIGRAVITY_API_KEYS")
        self.antigravity_rotator.log_key_count()

        self.cli_proxy_api_rotator = KeyRotator("CLIProxyAPI", "CLI_PROXY_API_KEYS")
        self.cli_proxy_api_rotator.log_key_count()

        self.cli_proxy_api_plus_rotator = KeyRotator("CLIProxyAPIPlus", "CLI_PROXY_API_KEYS")
        self.cli_proxy_api_plus_rotator.log_key_count()

        self.ccs_rotator = KeyRotator("CCS", "CCS_API_KEYS")
        self.ccs_rotator.log_key_count()

        self.opencode_rotator = KeyRotator("OpenCode", "OPENCODE_API_KEYS")
        self.opencode_rotator.log_key_count()