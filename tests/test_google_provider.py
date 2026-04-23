# -*- coding: utf-8 -*-
import unittest

from src.providers.google import GoogleApiClient


class GoogleSchemaSanitizationTests(unittest.TestCase):
    """Google Gemini API schema 변환 테스트"""

    def test_allOf_is_preserved_in_schema(self) -> None:
        """allOf 키가 보존되어야 함"""
        schema = {
            "type": "object",
            "allOf": [
                {"type": "object", "properties": {"name": {"type": "string"}}},
                {"type": "object", "properties": {"age": {"type": "integer"}}},
            ],
        }

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertEqual(sanitized["type"], "object")
        self.assertIn("allOf", sanitized)
        self.assertEqual(len(sanitized["allOf"]), 2)

    def test_ref_with_sibling_preserves_sibling_info(self) -> None:
        """$ref가 있어도 sibling 정보(type, description 등)는 보존되어야 함"""
        schema = {
            "$ref": "#/definitions/MyType",
            "type": "string",
            "description": "A referenced type",
        }

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertNotIn("$ref", sanitized)
        self.assertEqual(sanitized["type"], "string")
        self.assertEqual(sanitized["description"], "A referenced type")

    def test_ref_without_sibling_returns_empty_object(self) -> None:
        """$ref만 있고 sibling 정보가 없으면 빈 object 반환"""
        schema = {"$ref": "#/definitions/MyType"}

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertEqual(sanitized["type"], "object")
        self.assertIn("properties", sanitized)
        self.assertEqual(sanitized["properties"], {})

    def test_nested_properties_are_recursively_sanitized(self) -> None:
        """중첩된 properties도 재귀적으로 처리됨"""
        schema = {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "theme": {"type": "string", "format": "email"},
                        "options": {"type": "object", "title": "Options"},
                    },
                    "additionalProperties": False,
                },
                "metadata": {"type": "object"},
            },
        }

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        # 최상위 유지
        self.assertEqual(sanitized["type"], "object")
        self.assertIn("properties", sanitized)

        # 중첩 properties
        config_prop = sanitized["properties"]["config"]
        self.assertEqual(config_prop["type"], "object")
        self.assertNotIn("additionalProperties", config_prop)

        # format은 제거됨 (UNSUPPORTED)
        theme_prop = config_prop["properties"]["theme"]
        self.assertEqual(theme_prop["type"], "string")
        self.assertNotIn("format", theme_prop)

        # title은 제거됨 (UNSUPPORTED)
        options_prop = config_prop["properties"]["options"]
        self.assertNotIn("title", options_prop)
        self.assertIn("properties", options_prop)

    def test_const_converts_to_enum(self) -> None:
        """const는 enum으로 변환됨"""
        schema = {"type": "string", "const": "fixed_value"}

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertNotIn("const", sanitized)
        self.assertEqual(sanitized["enum"], ["fixed_value"])

    def test_const_with_existing_enum_preserves_enum(self) -> None:
        """기존 enum이 있으면 const를 덮어쓰지 않음"""
        schema = {"type": "string", "const": "fixed", "enum": ["a", "b"]}

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertEqual(sanitized["enum"], ["a", "b"])

    def test_anyOf_oneOf_allOf_preserved(self) -> None:
        """anyOf, oneOf, allOf 모두 보존됨"""
        schema = {
            "type": "object",
            "anyOf": [{"type": "string"}, {"type": "number"}],
            "oneOf": [{"type": "boolean"}],
            "allOf": [{"type": "object", "properties": {"x": {"type": "integer"}}}],
        }

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertIn("anyOf", sanitized)
        self.assertIn("oneOf", sanitized)
        self.assertIn("allOf", sanitized)
        self.assertEqual(len(sanitized["anyOf"]), 2)
        self.assertEqual(len(sanitized["oneOf"]), 1)
        self.assertEqual(len(sanitized["allOf"]), 1)

    def test_items_is_recursively_sanitized(self) -> None:
        """items도 재귀적으로 처리됨"""
        schema = {
            "type": "array",
            "items": {"type": "string", "format": "date", "title": "DateItem"},
        }

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertEqual(sanitized["type"], "array")
        self.assertIn("items", sanitized)
        items = sanitized["items"]
        self.assertEqual(items["type"], "string")
        self.assertNotIn("format", items)
        self.assertNotIn("title", items)

    def test_required_preserved_as_string_list(self) -> None:
        """required는 문자열 리스트로 보존됨"""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name", "age", 123, None],
        }

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertEqual(sanitized["required"], ["name", "age"])

    def test_enum_preserves_valid_types(self) -> None:
        """enum은 유효한 타입만 보존됨"""
        schema = {"type": "string", "enum": ["a", 1, 2.5, True, None, {"invalid": "dict"}]}

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertEqual(sanitized["enum"], ["a", 1, 2.5, True])

    def test_type_inferred_from_properties(self) -> None:
        """type이 없어도 properties가 있으면 object로 설정됨"""
        schema = {"properties": {"name": {"type": "string"}}}

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertEqual(sanitized["type"], "object")

    def test_type_inferred_from_items(self) -> None:
        """type이 없어도 items가 있으면 array로 설정됨"""
        schema = {"items": {"type": "string"}}

        sanitized = GoogleApiClient._sanitize_schema_for_google(schema)

        self.assertEqual(sanitized["type"], "array")


class GoogleToolConversionTests(unittest.TestCase):
    """Google Gemini API tool 변환 테스트"""

    def test_convert_tools_with_valid_schema(self) -> None:
        """유효한 schema를 가진 tool 변환"""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather info",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City name",
                            }
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

        result = GoogleApiClient._convert_tools(tools)

        self.assertEqual(len(result), 1)
        self.assertIn("functionDeclarations", result[0])
        declarations = result[0]["functionDeclarations"]
        self.assertEqual(len(declarations), 1)

        decl = declarations[0]
        self.assertEqual(decl["name"], "get_weather")
        self.assertEqual(decl["description"], "Get weather info")

        # parameters의 type이 Gemini 형식으로 변환됨
        params = decl["parameters"]
        self.assertEqual(params["type"], "OBJECT")
        self.assertIn("properties", params)
        self.assertEqual(params["properties"]["location"]["type"], "STRING")

    def test_convert_tools_filters_non_function_tools(self) -> None:
        """function 타입이 아닌 tool은 무시됨"""
        tools = [
            {"type": "function", "function": {"name": "valid_tool"}},
            {"type": "other", "function": {"name": "invalid_tool"}},
        ]

        result = GoogleApiClient._convert_tools(tools)

        self.assertEqual(len(result), 1)
        declarations = result[0]["functionDeclarations"]
        self.assertEqual(len(declarations), 1)
        self.assertEqual(declarations[0]["name"], "valid_tool")

    def test_convert_tools_skips_tool_without_name(self) -> None:
        """이름이 없는 tool은 무시됨"""
        tools = [
            {"type": "function", "function": {"description": "No name"}},
            {"type": "function", "function": {"name": "valid"}},
        ]

        result = GoogleApiClient._convert_tools(tools)

        self.assertEqual(len(result), 1)
        declarations = result[0]["functionDeclarations"]
        self.assertEqual(len(declarations), 1)
        self.assertEqual(declarations[0]["name"], "valid")

    def test_convert_tools_empty_tools_returns_empty_list(self) -> None:
        """빈 tool 리스트는 빈 리스트 반환"""
        result = GoogleApiClient._convert_tools([])
        self.assertEqual(result, [])

        result = GoogleApiClient._convert_tools(None)
        self.assertEqual(result, [])


class GoogleToolChoiceConversionTests(unittest.TestCase):
    """Google Gemini API tool_choice 변환 테스트"""

    def test_tool_choice_auto_maps_to_AUTO(self) -> None:
        """'auto' -> 'AUTO'로 매핑"""
        result = GoogleApiClient._convert_tool_choice("auto")

        self.assertEqual(result, {"functionCallingConfig": {"mode": "AUTO"}})

    def test_tool_choice_none_maps_to_NONE(self) -> None:
        """'none' -> 'NONE'으로 매핑"""
        result = GoogleApiClient._convert_tool_choice("none")

        self.assertEqual(result, {"functionCallingConfig": {"mode": "NONE"}})

    def test_tool_choice_required_maps_to_ANY(self) -> None:
        """'required' -> 'ANY'로 매핑"""
        result = GoogleApiClient._convert_tool_choice("required")

        self.assertEqual(result, {"functionCallingConfig": {"mode": "ANY"}})

    def test_tool_choice_function_name_in_allowed_function_names(self) -> None:
        """특정 함수 이름 지정 시 allowedFunctionNames에 포함"""
        tool_choice = {"type": "function", "function": {"name": "my_tool"}}

        result = GoogleApiClient._convert_tool_choice(tool_choice)

        self.assertEqual(
            result,
            {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["my_tool"],
                }
            },
        )

    def test_tool_choice_none_returns_none(self) -> None:
        """None은 None 반환"""
        result = GoogleApiClient._convert_tool_choice(None)
        self.assertIsNone(result)

    def test_tool_choice_unknown_string_returns_none(self) -> None:
        """알 수 없는 문자열은 None 반환"""
        result = GoogleApiClient._convert_tool_choice("unknown")
        self.assertIsNone(result)


class GoogleSchemaTypeConversionTests(unittest.TestCase):
    """Google Gemini API schema type 변환 테스트"""

    def test_type_string_converts_to_STRING(self) -> None:
        """string -> STRING으로 변환"""
        schema = {"type": "string"}
        result = GoogleApiClient._convert_schema_types(schema)
        self.assertEqual(result["type"], "STRING")

    def test_type_number_converts_to_NUMBER(self) -> None:
        """number -> NUMBER로 변환"""
        schema = {"type": "number"}
        result = GoogleApiClient._convert_schema_types(schema)
        self.assertEqual(result["type"], "NUMBER")

    def test_type_integer_converts_to_INTEGER(self) -> None:
        """integer -> INTEGER로 변환"""
        schema = {"type": "integer"}
        result = GoogleApiClient._convert_schema_types(schema)
        self.assertEqual(result["type"], "INTEGER")

    def test_type_boolean_converts_to_BOOLEAN(self) -> None:
        """boolean -> BOOLEAN으로 변환"""
        schema = {"type": "boolean"}
        result = GoogleApiClient._convert_schema_types(schema)
        self.assertEqual(result["type"], "BOOLEAN")

    def test_type_array_converts_to_ARRAY(self) -> None:
        """array -> ARRAY로 변환"""
        schema = {"type": "array"}
        result = GoogleApiClient._convert_schema_types(schema)
        self.assertEqual(result["type"], "ARRAY")

    def test_type_object_converts_to_OBJECT(self) -> None:
        """object -> OBJECT로 변환"""
        schema = {"type": "object"}
        result = GoogleApiClient._convert_schema_types(schema)
        self.assertEqual(result["type"], "OBJECT")

    def test_nested_type_conversion_in_properties(self) -> None:
        """중첩된 properties 내의 type도 변환됨"""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
            },
        }

        result = GoogleApiClient._convert_schema_types(schema)

        self.assertEqual(result["type"], "OBJECT")
        self.assertEqual(result["properties"]["name"]["type"], "STRING")
        self.assertEqual(result["properties"]["count"]["type"], "INTEGER")

    def test_nested_type_conversion_in_items(self) -> None:
        """items 내의 type도 변환됨"""
        schema = {"type": "array", "items": {"type": "string"}}

        result = GoogleApiClient._convert_schema_types(schema)

        self.assertEqual(result["type"], "ARRAY")
        self.assertEqual(result["items"]["type"], "STRING")

    def test_nested_type_conversion_in_anyOf(self) -> None:
        """anyOf 내의 type도 변환됨"""
        schema = {
            "anyOf": [
                {"type": "string"},
                {"type": "number"},
            ]
        }

        result = GoogleApiClient._convert_schema_types(schema)

        self.assertEqual(result["anyOf"][0]["type"], "STRING")
        self.assertEqual(result["anyOf"][1]["type"], "NUMBER")


class GoogleIntegrationTests(unittest.TestCase):
    """Google provider 통합 테스트"""

    def test_full_tool_conversion_pipeline(self) -> None:
        """전체 tool 변환 파이프라인 테스트"""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path",
                            },
                            "pages": {
                                "type": "string",
                                "description": "Page range",
                                "default": "1-5",
                            },
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                        "$schema": "http://json-schema.org/draft-07/schema#",
                    },
                },
            }
        ]

        result = GoogleApiClient._convert_tools(tools)

        self.assertEqual(len(result), 1)
        decl = result[0]["functionDeclarations"][0]
        self.assertEqual(decl["name"], "read_file")
        self.assertEqual(decl["description"], "Read a file")

        params = decl["parameters"]
        self.assertEqual(params["type"], "OBJECT")
        self.assertIn("path", params["properties"])
        self.assertIn("pages", params["properties"])

        # default는 제거됨 (UNSUPPORTED)
        self.assertNotIn("default", params["properties"]["pages"])

        # additionalProperties 제거됨
        self.assertNotIn("additionalProperties", params)

        # $schema 제거됨
        self.assertNotIn("$schema", params)

        # required는 보존됨
        self.assertEqual(params["required"], ["path"])


if __name__ == "__main__":
    unittest.main()