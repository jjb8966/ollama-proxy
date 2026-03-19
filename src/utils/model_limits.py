# -*- coding: utf-8 -*-
"""
모델 한도 조회 유틸리티

models.json 에서 모델별 context 및 output 한도를 읽어옵니다.
"""

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ModelLimits:
    context_length: Optional[int]
    max_output_tokens: Optional[int]


_MODEL_LIMITS_CACHE: Dict[str, ModelLimits] = {}

_ALIASES = {
    "ollama:": "ollama-cloud:",
}


def _models_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "models.json",
    )


def _normalize_model_name(model_name: str) -> str:
    normalized = model_name
    for prefix, replacement in _ALIASES.items():
        if normalized.startswith(prefix):
            return normalized.replace(prefix, replacement, 1)
    return normalized


def load_model_limits() -> Dict[str, ModelLimits]:
    limits: Dict[str, ModelLimits] = {}

    try:
        with open(_models_path(), "r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return limits

    for item in data.get("models", []):
        if not isinstance(item, dict):
            continue

        context_length = item.get("context_length")
        max_output_tokens = item.get("max_output_tokens")
        normalized_context_length = context_length if isinstance(context_length, int) else None
        normalized_max_output_tokens = max_output_tokens if isinstance(max_output_tokens, int) else normalized_context_length
        limits_value = ModelLimits(
            context_length=normalized_context_length,
            max_output_tokens=normalized_max_output_tokens,
        )

        for key in (item.get("name"), item.get("model")):
            if not isinstance(key, str) or not key:
                continue
            limits[_normalize_model_name(key)] = limits_value

    return limits


def get_model_limits(model_name: str) -> Optional[ModelLimits]:
    global _MODEL_LIMITS_CACHE

    if not isinstance(model_name, str) or not model_name:
        return None

    if not _MODEL_LIMITS_CACHE:
        _MODEL_LIMITS_CACHE = load_model_limits()

    return _MODEL_LIMITS_CACHE.get(_normalize_model_name(model_name))


def reset_model_limits_cache() -> None:
    global _MODEL_LIMITS_CACHE
    _MODEL_LIMITS_CACHE = {}
