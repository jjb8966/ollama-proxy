# -*- coding: utf-8 -*-
"""
프로바이더별 base URL 및 클라이언트 속성 매핑
"""

import os
from typing import Any, Dict, Optional


def _strip_quotes(value: str) -> str:
    if not value:
        return value
    return value.strip('"\'')


PROVIDER_CONFIG: Dict[str, Dict[str, Any]] = {
    "antigravity": {
        "base_url": _strip_quotes(
            os.getenv("ANTIGRAVITY_PROXY_URL", "http://antigravity-proxy:5010/v1")
        ),
        "client_attr": "antigravity_client",
        "auth": "standard",
        "rotator_attr": "antigravity_rotator",
    },
    "cli-proxy-api": {
        "base_url": _strip_quotes(
            os.getenv("CLI_PROXY_API_BASE_URL", "http://cli-proxy-api:8317/v1")
        ),
        "client_attr": "cli_proxy_api_client",
        "auth": "standard",
        "rotator_attr": "cli_proxy_api_rotator",
    },
    "cli-proxy-api-plus": {
        "base_url": _strip_quotes(
            os.getenv("CLI_PROXY_API_PLUS_BASE_URL", "http://cli-proxy-api-plus:8317/v1")
        ),
        "client_attr": "cli_proxy_api_plus_client",
        "auth": "standard",
        "rotator_attr": "cli_proxy_api_plus_rotator",
    },
    "ccs": {
        "base_url": _strip_quotes(
            os.getenv("CCS_API_BASE_URL", "http://ccs:8317/api/provider/cursor/v1")
        ),
        "client_attr": "ccs_client",
        "auth": "standard",
        "rotator_attr": "ccs_rotator",
    },
    "opencode": {
        "base_url": _strip_quotes(
            os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")
        ),
        "client_attr": "opencode_client",
        "auth": "standard",
        "rotator_attr": "opencode_rotator",
    },
}

CATALOG_PROVIDER_PREFIXES = tuple(
    prefix
    for prefix, cfg in PROVIDER_CONFIG.items()
    if cfg.get("list_in_catalog", True)
)


def parse_provider_model(requested_model: str) -> tuple[Optional[str], str, Optional[str]]:
    """요청 모델 문자열에서 (provider, upstream_model, base_url) 반환"""
    for prefix, config in PROVIDER_CONFIG.items():
        marker = f"{prefix}:"
        if requested_model.startswith(marker):
            upstream = requested_model[len(marker):]
            return prefix, upstream, config.get("base_url")
    return None, requested_model, None