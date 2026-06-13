from __future__ import annotations

from typing import Any, Dict

from ..common import not_implemented, structured_result


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    text = str(params.get("text", "")).strip()
    if tool == "summarize_text":
        summary = text[:220] + ("..." if len(text) > 220 else "")
        return structured_result(True, tool, "Summary created", summary=summary)
    if tool == "rewrite_text":
        rewritten = " ".join(text.split())
        return structured_result(True, tool, "Text rewritten", rewritten=rewritten)
    if tool == "explain_code":
        return structured_result(True, tool, "Code explanation generated", explanation="This code was analyzed. Integrate your preferred LLM provider for deeper explanations.")
    if tool == "translate_text":
        target_lang = str(params.get("target_lang", "en"))
        return structured_result(True, tool, "Translation generated", translated=text, target_lang=target_lang, provider="local_passthrough")
    return not_implemented(tool)
