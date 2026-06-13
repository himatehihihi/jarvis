"""Validation layer between planner output and executor/hands execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any, Dict, List, Optional

from .tool_registry import canonical_tool_name, get_tool


TYPE_CHECKERS = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
}


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    tool_name: Optional[str] = None
    tool_spec: Optional[Dict[str, Any]] = None
    normalized_parameters: Dict[str, Any] = field(default_factory=dict)
    executor_intent: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "tool_name": self.tool_name,
            "tool_spec": self.tool_spec,
            "normalized_parameters": self.normalized_parameters,
            "executor_intent": self.executor_intent,
        }


def _coerce_number_bounds(key: str, schema: Dict[str, Any], value: Any) -> Optional[str]:
    min_value = schema.get("min")
    max_value = schema.get("max")
    if min_value is not None and value < min_value:
        return f"Parameter '{key}' must be >= {min_value}."
    if max_value is not None and value > max_value:
        return f"Parameter '{key}' must be <= {max_value}."
    return None


def validate_tool_call(
    tool_name: str,
    parameters: Optional[Dict[str, Any]] = None,
    confirmed: bool = False,
    allow_blocked: bool = False,
) -> ValidationResult:
    params = parameters or {}
    result = ValidationResult(ok=False)

    canonical = canonical_tool_name(tool_name)
    if not canonical:
        result.errors.append(f"Unknown tool: '{tool_name}'.")
        return result

    spec = get_tool(canonical)
    if not spec:
        result.errors.append(f"Tool not found in registry: '{canonical}'.")
        return result

    result.tool_name = canonical
    result.tool_spec = spec

    safety = spec.get("safety_level", "SAFE")
    if safety == "CONFIRM_REQUIRED" and not confirmed:
        result.errors.append(f"Tool '{canonical}' requires confirmation.")
    if safety == "BLOCKED_UNLESS_ENABLED" and not allow_blocked:
        result.errors.append(f"Tool '{canonical}' is blocked unless explicitly enabled.")

    expected = spec.get("parameters", {})
    normalized: Dict[str, Any] = {}

    for key, schema in expected.items():
        is_required = bool(schema.get("required", False))
        value = params.get(key)

        if (value is None or value == "") and is_required:
            result.errors.append(f"Missing required parameter: '{key}'.")
            continue

        if value is None:
            continue

        declared_type = schema.get("type", "string")
        checker = TYPE_CHECKERS.get(declared_type)
        if checker and not checker(value):
            result.errors.append(f"Parameter '{key}' must be of type {declared_type}.")
            continue

        if declared_type in ("integer", "number"):
            bounds_error = _coerce_number_bounds(key, schema, value)
            if bounds_error:
                result.errors.append(bounds_error)
                continue

        normalized[key] = value

    for key in params.keys():
        if key not in expected:
            result.warnings.append(f"Unknown parameter ignored: '{key}'.")

    if result.errors:
        return result

    result.normalized_parameters = normalized
    result.executor_intent = {
        "intent": "tool_execute",
        "tool": canonical,
        "parameters": normalized,
    }
    result.ok = True
    return result


def validate_planner_output(plan: Dict[str, Any], confirmed: bool = False, allow_blocked: bool = False) -> ValidationResult:
    tools = plan.get("tools") or []
    top_tool = plan.get("tool")
    top_params = plan.get("parameters", {})
    if not tools and not top_tool:
        return ValidationResult(ok=False, errors=["Planner output has no tool selection."])

    first = tools[0] if tools and isinstance(tools[0], dict) else {}
    tool_name = first.get("name") or top_tool or ""
    parameters = first.get("parameters") if isinstance(first.get("parameters"), dict) else top_params
    return validate_tool_call(str(tool_name), parameters=parameters, confirmed=confirmed, allow_blocked=allow_blocked)


def canonicalize_planner_output(plan: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(plan) if isinstance(plan, dict) else {}
    top_tool = out.get("tool")
    if top_tool:
        canonical_top = canonical_tool_name(str(top_tool))
        if canonical_top and canonical_top != top_tool:
            out["tool_alias_normalized_from"] = top_tool
            out["tool"] = canonical_top

    tools = out.get("tools")
    if not isinstance(tools, list):
        return out

    normalized_tools = []
    for item in tools:
        if not isinstance(item, dict):
            normalized_tools.append(item)
            continue
        tool_name = item.get("name", "")
        canonical = canonical_tool_name(str(tool_name)) if tool_name else None
        fixed = dict(item)
        if canonical:
            fixed["name"] = canonical
            if canonical != tool_name:
                fixed["alias_normalized_from"] = tool_name
        normalized_tools.append(fixed)

    out["tools"] = normalized_tools
    return out
