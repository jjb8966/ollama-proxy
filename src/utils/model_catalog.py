# -*- coding: utf-8 -*-
"""
프로바이더 /models 엔드포인트에서 모델 목록을 동적으로 조회합니다.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

from src.providers.provider_config import (
    CATALOG_PROVIDER_PREFIXES,
    PROVIDER_CONFIG,
)
from src.utils.model_limits import get_model_limits

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = (10, 30)
DEFAULT_CACHE_TTL_SECONDS = 300

_catalog_cache: List[Dict[str, Any]] = []
_catalog_cached_at: float = 0.0


def reset_model_catalog_cache() -> None:
    global _catalog_cache, _catalog_cached_at
    _catalog_cache = []
    _catalog_cached_at = 0.0


def _cache_ttl_seconds() -> int:
    raw = os.environ.get("MODEL_CATALOG_TTL_SECONDS", str(DEFAULT_CACHE_TTL_SECONDS))
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_CACHE_TTL_SECONDS


def _normalize_upstream_model_id(raw_id: str) -> str:
    value = raw_id.strip()
    if value.startswith("models/"):
        return value[len("models/"):]
    return value


def _extract_model_ids_from_payload(payload: Any) -> List[str]:
    if not isinstance(payload, dict):
        return []

    ids: List[str] = []

    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                model_id = item.get("id") or item.get("name")
                if isinstance(model_id, str) and model_id.strip():
                    ids.append(_normalize_upstream_model_id(model_id))

    models = payload.get("models")
    if isinstance(models, list):
        for item in models:
            if isinstance(item, str) and item.strip():
                ids.append(_normalize_upstream_model_id(item))
                continue
            if isinstance(item, dict):
                model_id = item.get("id") or item.get("name") or item.get("model")
                if isinstance(model_id, str) and model_id.strip():
                    ids.append(_normalize_upstream_model_id(model_id))

    return ids


def _get_standard_bearer_token(api_config: Any, rotator_attr: str) -> Optional[str]:
    rotator = getattr(api_config, rotator_attr, None)
    if rotator is None:
        return None
    api_keys = getattr(rotator, "api_keys", None)
    if not api_keys:
        return None
    key = rotator.get_next_key()
    if not key:
        return None
    return key


def _fetch_openai_compatible_models(base_url: str, bearer_token: str) -> List[str]:
    url = f"{base_url.rstrip('/')}/models"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return _extract_model_ids_from_payload(resp.json())


def _fetch_provider_upstream_models(provider: str, api_config: Any) -> List[str]:
    config = PROVIDER_CONFIG[provider]
    base_url = config.get("base_url")
    rotator_attr = config.get("rotator_attr")
    if not base_url or not rotator_attr:
        return []

    token = _get_standard_bearer_token(api_config, rotator_attr)
    if not token:
        return []

    return _fetch_openai_compatible_models(base_url, token)


def _attach_limits_metadata(entry: Dict[str, Any], proxy_model_id: str) -> None:
    limits = get_model_limits(proxy_model_id)
    if limits is None:
        return
    if limits.context_length is not None:
        entry["context_length"] = limits.context_length
    if limits.max_output_tokens is not None:
        entry["max_output_tokens"] = limits.max_output_tokens


def _build_catalog_entry(provider: str, upstream_model_id: str) -> Dict[str, Any]:
    proxy_model_id = f"{provider}:{upstream_model_id}"
    entry: Dict[str, Any] = {
        "name": proxy_model_id,
        "model": proxy_model_id,
    }
    _attach_limits_metadata(entry, proxy_model_id)
    return entry


def load_model_catalog(api_config: Any, *, force_refresh: bool = False) -> List[Dict[str, Any]]:
    global _catalog_cache, _catalog_cached_at

    ttl = _cache_ttl_seconds()
    now = time.time()
    if (
        not force_refresh
        and _catalog_cache
        and ttl > 0
        and (now - _catalog_cached_at) < ttl
    ):
        return list(_catalog_cache)

    merged: Dict[str, Dict[str, Any]] = {}

    for provider in CATALOG_PROVIDER_PREFIXES:
        try:
            upstream_ids = _fetch_provider_upstream_models(provider, api_config)
        except requests.RequestException as exc:
            logger.warning(
                "[ModelCatalog] 프로바이더 모델 조회 실패 | provider=%s | error=%s",
                provider,
                exc,
            )
            continue
        except Exception as exc:
            logger.warning(
                "[ModelCatalog] 프로바이더 모델 조회 예외 | provider=%s | error=%s",
                provider,
                exc,
            )
            continue

        for upstream_id in upstream_ids:
            if not upstream_id:
                continue
            entry = _build_catalog_entry(provider, upstream_id)
            merged[entry["model"]] = entry

    catalog = sorted(merged.values(), key=lambda item: item["model"])
    _catalog_cache = catalog
    _catalog_cached_at = now
    return list(catalog)


def extract_upstream_model_ids(payload: Any) -> List[str]:
    return _extract_model_ids_from_payload(payload)


def list_model_entries_for_tags(api_config: Any, *, force_refresh: bool = False) -> List[Dict[str, Any]]:
    return load_model_catalog(api_config, force_refresh=force_refresh)


def load_available_models(api_config: Any, *, force_refresh: bool = False) -> List[Dict[str, Any]]:
    return load_model_catalog(api_config, force_refresh=force_refresh)