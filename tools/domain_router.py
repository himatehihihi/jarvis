"""Domain-first routing to avoid exposing the full tool space to the planner."""

from __future__ import annotations

from typing import Any, Dict, List

from .tool_registry import list_domains, list_tools_by_domain


def route_domain(domain: str) -> List[Dict[str, Any]]:
    """Return only tools for a selected domain."""
    return list_tools_by_domain(domain)


def available_domains() -> List[str]:
    return list_domains()


def build_domain_context() -> Dict[str, List[Dict[str, str]]]:
    """Compact prompt context for AI: domain -> [{tool, description}]."""
    context: Dict[str, List[Dict[str, str]]] = {}
    for domain in available_domains():
        context[domain] = [
            {"tool": tool["tool"], "description": tool.get("description", "")}
            for tool in route_domain(domain)
        ]
    return context


def route_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Attach narrowed tool candidates to the AI plan based on selected domain."""
    domain = str(plan.get("domain", "")).strip().lower()
    narrowed = route_domain(domain) if domain else []
    out = dict(plan)
    out["domain_candidates"] = narrowed
    out["domain_valid"] = bool(narrowed)
    return out
