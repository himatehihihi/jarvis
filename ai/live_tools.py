"""Bridge the existing Jarvis tool registry into Gemini function calling."""

from __future__ import annotations

from typing import Any, Dict, List

from google.genai import types

from tools.executor_router import execute_tool
from tools.tool_registry import list_tools
from tools.tool_validator import validate_tool_call


JSON_TYPE_MAP = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "object": "object",
    "array": "array",
}


def _parameter_json_schema(spec: Dict[str, Any]) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for name, schema in (spec.get("parameters") or {}).items():
        prop: Dict[str, Any] = {
            "type": JSON_TYPE_MAP.get(str(schema.get("type", "string")), "string"),
            "description": f"Parameter {name} for {spec.get('tool')}.",
        }
        if "min" in schema:
            prop["minimum"] = schema["min"]
        if "max" in schema:
            prop["maximum"] = schema["max"]
        properties[name] = prop
        if schema.get("required"):
            required.append(name)
    out: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        out["required"] = required
    return out


def build_live_tool_declarations() -> list[types.Tool]:
    declarations: List[types.FunctionDeclaration] = []
    for spec in list_tools():
        declarations.append(
            types.FunctionDeclaration(
                name=str(spec.get("tool", "")),
                description=str(spec.get("description", "")),
                parameters_json_schema=_parameter_json_schema(spec),
            )
        )
    return [types.Tool(function_declarations=declarations)]


def execute_live_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    validation = validate_tool_call(tool_name, args, confirmed=False, allow_blocked=False)
    if not validation.ok:
        return {
            "success": False,
            "tool": tool_name,
            "error": "; ".join(validation.errors) or "Tool validation failed",
            "warnings": validation.warnings,
        }
    result = execute_tool(validation.tool_name or tool_name, validation.normalized_parameters)
    if isinstance(result, dict):
        return result
    return {"success": bool(result), "tool": validation.tool_name or tool_name, "message": str(result)}
