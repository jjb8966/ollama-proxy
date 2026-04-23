# -*- coding: utf-8 -*-
"""
스키마 정규화 유틸리티

Google, Anthropic 등 프로바이더별 JSON Schema 정규화 로직을 공통화합니다.
"""
from typing import Any, Dict, Optional, Set


SCHEMA_ALLOWED_KEYS: Set[str] = {
    "type",
    "description",
    "enum",
    "items",
    "properties",
    "required",
    "nullable",
    "anyOf",
    "oneOf",
    "allOf",
}

GOOGLE_UNSUPPORTED_CONSTRAINT_KEYS: Set[str] = {
    "minLength",
    "maxLength",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "pattern",
    "minItems",
    "maxItems",
    "format",
    "default",
    "examples",
}

GOOGLE_UNSUPPORTED_SCHEMA_KEYS: Set[str] = {
    "$schema",
    "$defs",
    "definitions",
    "$ref",
    "const",
    "additionalProperties",
    "patternProperties",
    "unevaluatedProperties",
    "dependentSchemas",
    "propertyNames",
    "title",
    "$id",
    "$comment",
}


def sanitize_schema(
    schema: Any,
    allowed_keys: Set[str] = SCHEMA_ALLOWED_KEYS,
    unsupported_constraint_keys: Optional[Set[str]] = None,
    unsupported_schema_keys: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """JSON Schema를 프로바이더 호환 형태로 정규화합니다.

    Args:
        schema: 원본 스키마 (dict 또는 기타)
        allowed_keys: 허용할 스키마 키 집합
        unsupported_constraint_keys: 제거할 제약 키 집합 (Google 전용)
        unsupported_schema_keys: 제거할 메타 스키마 키 집합 (Google 전용)

    Returns:
        정규화된 스키마 딕셔너리
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    # Google 전용: const → enum 변환
    working = dict(schema)
    if unsupported_schema_keys is not None:
        if "const" in working and "enum" not in working:
            working["enum"] = [working["const"]]

    result: Dict[str, Any] = {}
    for key, value in working.items():
        # 허용 키 필터링
        if key not in allowed_keys:
            continue
        # Google 전용 제약 키 필터링
        if unsupported_constraint_keys and key in unsupported_constraint_keys:
            continue
        # Google 전용 메타 스키마 키 필터링
        if unsupported_schema_keys and key in unsupported_schema_keys:
            continue

        if key == "properties":
            if not isinstance(value, dict):
                continue
            result["properties"] = {
                prop_name: sanitize_schema(
                    prop_schema, allowed_keys,
                    unsupported_constraint_keys, unsupported_schema_keys
                )
                for prop_name, prop_schema in value.items()
                if isinstance(prop_name, str)
            }
            continue

        if key == "items":
            if isinstance(value, dict):
                result["items"] = sanitize_schema(
                    value, allowed_keys,
                    unsupported_constraint_keys, unsupported_schema_keys
                )
            continue

        if key in ("anyOf", "oneOf", "allOf"):
            if isinstance(value, list):
                variants = [
                    sanitize_schema(
                        item, allowed_keys,
                        unsupported_constraint_keys, unsupported_schema_keys
                    )
                    for item in value if isinstance(item, dict)
                ]
                if variants:
                    result[key] = variants
            continue

        # Google 전용: required 값을 string만 필터링
        if key == "required":
            if isinstance(value, list):
                result["required"] = [item for item in value if isinstance(item, str)]
            continue

        # Google 전용: enum 값을 허용 타입만 필터링
        if key == "enum":
            if isinstance(value, list):
                result["enum"] = [
                    item for item in value
                    if isinstance(item, (str, int, float, bool))
                ]
            continue

        result[key] = value

    # Google 전용: 빈 결과 시 기본값
    if unsupported_schema_keys is not None and not result:
        return {"type": "object", "properties": {}}

    # type 추론 (Google 전용)
    if unsupported_schema_keys is not None and "type" not in result:
        if "properties" in result:
            result["type"] = "object"
        elif "items" in result:
            result["type"] = "array"

    # object type인데 properties 없으면 빈 dict 추가
    if result.get("type") == "object" and "properties" not in result:
        result["properties"] = {}

    return result
