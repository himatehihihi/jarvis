"""Planner context compression and retrieval scaffolding."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Set

from tools.tool_registry import list_domains, list_tools_by_domain


TOKEN_BUDGET = int(os.getenv("JARVIS_PLANNER_TOKEN_BUDGET", "700"))
MAX_DOMAINS = int(os.getenv("JARVIS_PLANNER_MAX_DOMAINS", "3"))
MAX_TOOLS = int(os.getenv("JARVIS_PLANNER_MAX_TOOLS", "14"))


DOMAIN_KEYWORDS: Dict[str, Sequence[str]] = {
    "system": ("open", "launch", "start", "shutdown", "restart", "volume", "brightness"),
    "windows": ("window", "switch", "minimize", "maximize", "focus", "snap"),
    "filesystem": ("file", "folder", "rename", "copy", "move", "delete", "downloads", "zip"),
    "browser": ("website", "google", "youtube", "url", "browser", "search"),
    "productivity": ("note", "reminder", "timer", "focus", "task"),
    "developer": ("git", "python", "test", "package", "commit", "project"),
    "ai": ("summarize", "rewrite", "translate", "explain"),
    "media": ("play", "music", "song", "spotify", "youtube music", "pause", "track"),
    "vision": ("vision", "screen", "screenshot", "ocr", "image"),
    "communication": ("whatsapp", "message", "call", "video"),
    "diagnostics": ("diagnostics", "health", "slow", "recover", "memory", "cpu", "status"),
}


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class RetrievalResult:
    selected_domains: List[str]
    selected_tools: List[Dict[str, Any]]
    removed_tools: List[str]
    baseline_tokens: int
    compressed_tokens: int
    token_budget: int

    @property
    def reduction_percent(self) -> float:
        if self.baseline_tokens <= 0:
            return 0.0
        saved = max(0, self.baseline_tokens - self.compressed_tokens)
        return round((saved / self.baseline_tokens) * 100.0, 2)


class ToolRetriever:
    """Keyword-based retriever, designed to be replaceable by embeddings later."""

    def retrieve(self, query: str) -> RetrievalResult:
        text = str(query or "").lower().strip()
        all_domains = list_domains()
        all_tools = []
        for domain in all_domains:
            all_tools.extend(list_tools_by_domain(domain))

        baseline_context = [
            {"tool": spec.get("tool"), "params": sorted((spec.get("parameters") or {}).keys())}
            for spec in all_tools
        ]
        baseline_tokens = _estimate_tokens(str(baseline_context))

        scored: List[tuple[str, int]] = []
        for domain in all_domains:
            score = 0
            for keyword in DOMAIN_KEYWORDS.get(domain, ()):
                if keyword in text:
                    score += 2
            if domain in text:
                score += 3
            scored.append((domain, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        selected_domains = [domain for domain, score in scored if score > 0][:MAX_DOMAINS]
        if not selected_domains:
            selected_domains = ["system", "browser", "media"]

        selected: List[Dict[str, Any]] = []
        selected_names: Set[str] = set()
        for domain in selected_domains:
            specs = list_tools_by_domain(domain)
            tool_scores = []
            for spec in specs:
                name = str(spec.get("tool", ""))
                params = list((spec.get("parameters") or {}).keys())
                score = 0
                for part in name.split("_"):
                    if part and part in text:
                        score += 2
                for key in params:
                    if key in text:
                        score += 1
                if domain == "media" and name in {"play_song", "pause_media", "resume_media", "next_track", "previous_track"}:
                    score += 1
                tool_scores.append((spec, score))
            tool_scores.sort(key=lambda item: item[1], reverse=True)
            for spec, _ in tool_scores:
                compact = {"tool": spec.get("tool"), "params": sorted((spec.get("parameters") or {}).keys())}
                name = compact["tool"]
                if not name or name in selected_names:
                    continue
                selected.append(compact)
                selected_names.add(name)
                if len(selected) >= MAX_TOOLS:
                    break
            if len(selected) >= MAX_TOOLS:
                break

        compressed_tokens = _estimate_tokens(str(selected))
        removed_tools = [str(spec.get("tool")) for spec in all_tools if spec.get("tool") not in selected_names]
        return RetrievalResult(
            selected_domains=selected_domains,
            selected_tools=selected,
            removed_tools=removed_tools,
            baseline_tokens=baseline_tokens,
            compressed_tokens=compressed_tokens,
            token_budget=TOKEN_BUDGET,
        )


def build_compressed_tool_context(query: str) -> Dict[str, Any]:
    retriever = ToolRetriever()
    result = retriever.retrieve(query)
    return {
        "selected_domains": result.selected_domains,
        "allowed_tools": [item["tool"] for item in result.selected_tools],
        "tools": result.selected_tools,
        "token_budget": result.token_budget,
        "baseline_tokens": result.baseline_tokens,
        "compressed_tokens": result.compressed_tokens,
        "reduction_percent": result.reduction_percent,
        "budget_exceeded": result.compressed_tokens > result.token_budget,
        "removed_tools": result.removed_tools,
        "retrieval_strategy": "keyword_retriever_v1",
        "future_retrieval_hooks": {
            "semantic_tool_retrieval": False,
            "embedding_retrieval": False,
            "memory_aware_injection": False,
        },
    }
