from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import hands

from .executor_router import execute_tool


SAFE_RETRY_MAX_ATTEMPTS = 3
SAFE_RETRY_BASE_COOLDOWN_SECONDS = 0.35
DANGEROUS_TOOLS = {
    "delete_file",
    "shutdown_pc",
    "restart_pc",
    "sleep_pc",
    "git_commit",
    "run_python_script",
    "install_package",
    "run_tests",
}


def _log(message: str) -> None:
    print(f"[RETRY] {message}")


@dataclass
class RetryDecision:
    retry: bool
    reason: str
    strategy: str
    cooldown_s: float = 0.0


@dataclass
class RetryOutcome:
    success: bool
    attempts: int
    failure_class: str
    strategy: str
    history: List[Dict[str, Any]] = field(default_factory=list)
    final_result: Any = None


class RetryManager:
    def __init__(self, max_attempts: int = SAFE_RETRY_MAX_ATTEMPTS, base_cooldown: float = SAFE_RETRY_BASE_COOLDOWN_SECONDS):
        self.max_attempts = max_attempts
        self.base_cooldown = base_cooldown
        self.history: List[Dict[str, Any]] = []

    def classify_failure(self, result: Any = None, error: Exception | None = None) -> str:
        if isinstance(result, dict):
            if result.get("success"):
                return "none"
            text = str(result.get("error") or result.get("message") or result).lower()
        else:
            text = str(error or result or "").lower()
        if "timed out" in text or "timeout" in text:
            return "timeout"
        if "could not find" in text or "what app should i open" in text:
            return "missing_app"
        if "missing required parameter" in text or "must be of type" in text:
            return "invalid_params"
        if "url_error" in text or "connection" in text or "network" in text:
            return "network_failure"
        if "planner" in text:
            return "planner_failure"
        if "provider" in text or "unavailable" in text:
            return "provider_unavailable"
        return "tool_execution_failure"

    def can_retry_tool(self, tool_name: str) -> bool:
        return tool_name not in DANGEROUS_TOOLS

    def decide(self, context: Dict[str, Any], failure_class: str, attempt: int) -> RetryDecision:
        if attempt >= self.max_attempts:
            return RetryDecision(False, "max_retries_exceeded", "none")

        intent = str(context.get("intent", "")).lower()
        tool = str(context.get("tool", "")).lower()
        cooldown = self.base_cooldown * (2 ** (attempt - 1))

        if tool and not self.can_retry_tool(tool):
            return RetryDecision(False, "dangerous_tool_retry_blocked", "none")

        if intent in {"open_app", "open_known_target"} and failure_class in {"missing_app", "tool_execution_failure"}:
            return RetryDecision(True, "retry_with_alias_and_browser_fallback", "app_alias_browser_fallback", cooldown)
        if intent == "open_website" and failure_class in {"network_failure", "tool_execution_failure"}:
            return RetryDecision(True, "retry_with_search_fallback", "website_search_fallback", cooldown)
        if intent in {"web_search", "youtube_search"} and failure_class in {"network_failure", "tool_execution_failure"}:
            return RetryDecision(True, "retry_with_alternate_search", "alternate_search", cooldown)
        if intent == "play_song" and failure_class in {"tool_execution_failure", "missing_app"}:
            return RetryDecision(True, "retry_with_platform_fallback", "media_platform_fallback", cooldown)
        if tool in {"ai_health_check", "model_status", "performance_report", "run_full_diagnostics"} and failure_class in {"timeout", "provider_unavailable", "planner_failure"}:
            return RetryDecision(True, "trigger_ai_recovery_then_retry", "ai_recovery_retry", cooldown)
        if intent == "planner_failure" and failure_class in {"timeout", "planner_failure", "provider_unavailable", "network_failure"}:
            return RetryDecision(True, "retry_planner_with_backoff", "ai_recovery_retry", cooldown)

        if failure_class in {"timeout", "network_failure"}:
            return RetryDecision(True, "generic_backoff_retry", "backoff_retry", cooldown)
        return RetryDecision(False, "non_retryable_failure", "none")

    def _apply_strategy(self, strategy: str, context: Dict[str, Any], original_action: Callable[[], Any]) -> Any:
        intent = str(context.get("intent", "")).lower()
        payload = context.get("payload") if isinstance(context.get("payload"), dict) else {}

        if strategy == "app_alias_browser_fallback":
            target = str(payload.get("target", "")).strip().lower()
            if target in {"spotify", "spotify app"}:
                if hands.open_website("spotify"):
                    return True
            if target and hands.open_website(target):
                return True
            if target:
                return hands.search_google(target)
            return original_action()

        if strategy == "website_search_fallback":
            target = str(payload.get("target", "")).strip()
            if target:
                return hands.search_google(target)
            return original_action()

        if strategy == "alternate_search":
            query = str(payload.get("query", "")).strip()
            if query:
                return hands.search_google(query)
            return original_action()

        if strategy == "media_platform_fallback":
            query = str(payload.get("query", "")).strip()
            platform = str(payload.get("platform", "default")).strip().lower()
            if platform == "spotify":
                return hands.play_song(query, "youtube_music")
            return hands.play_song(query, "youtube")

        if strategy == "ai_recovery_retry":
            execute_tool("unload_models", {})
            execute_tool("recover_ai", {})
            return original_action()

        return original_action()

    def run_with_retry(self, context: Dict[str, Any], action: Callable[[], Any]) -> RetryOutcome:
        attempt = 1
        final = None
        failure_class = "none"
        strategy = "none"
        local_history: List[Dict[str, Any]] = []
        while attempt <= self.max_attempts:
            try:
                result = action() if attempt == 1 else self._apply_strategy(strategy, context, action)
            except Exception as exc:
                result = False
                failure_class = self.classify_failure(error=exc)
            else:
                failure_class = self.classify_failure(result=result) if not result else "none"

            ok = bool(result) if not isinstance(result, dict) else bool(result.get("success"))
            _log(f"attempt={attempt} success={ok} failure_class={failure_class}")
            local_history.append({"attempt": attempt, "success": ok, "failure_class": failure_class, "strategy": strategy})
            if ok:
                final = result
                break

            decision = self.decide(context, failure_class, attempt)
            strategy = decision.strategy
            _log(f"attempt={attempt} reason={decision.reason} strategy={decision.strategy}")
            if not decision.retry:
                final = result
                break
            if decision.cooldown_s > 0:
                time.sleep(decision.cooldown_s)
            attempt += 1
            final = result

        self.history.extend(local_history)
        return RetryOutcome(
            success=bool(final) if not isinstance(final, dict) else bool(final.get("success")),
            attempts=attempt,
            failure_class=failure_class,
            strategy=strategy,
            history=local_history,
            final_result=final,
        )
