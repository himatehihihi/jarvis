from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib import error, request

from ai.models import DEFAULT_OLLAMA_CONFIG
from ai.qwen_brain import check_ollama_connection, plan_with_qwen, warmup_qwen_model
from audio.runtime import get_pipeline
from tools.common import structured_result
from tools.tool_registry import list_tools
from tools.tool_validator import validate_tool_call


STATE_FILE = Path("memory.json").resolve().parent / "diagnostics_state.json"
SAFE_AVAILABLE_RAM_GB = float(os.getenv("JARVIS_SAFE_AVAILABLE_RAM_GB", "4.0"))
HEAVY_MODELS = ("llava", "qwen2.5-coder:7b", "qwen2.5")


def _log(scope: str, message: str) -> None:
    print(f"[{scope}] {message}")


def _read_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_state(data: Dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _safe_mode_enabled() -> bool:
    state = _read_state()
    return bool(state.get("safe_mode"))


def _ollama_call(path: str, method: str = "GET", payload: Dict[str, Any] | None = None, timeout: int = 15) -> Tuple[bool, Dict[str, Any], float, str]:
    url = f"{DEFAULT_OLLAMA_CONFIG.base_url.rstrip('/')}{path}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return True, raw, (time.perf_counter() - start) * 1000.0, ""
    except socket.timeout as exc:
        return False, {}, (time.perf_counter() - start) * 1000.0, f"socket_timeout: {exc}"
    except TimeoutError as exc:
        return False, {}, (time.perf_counter() - start) * 1000.0, f"timeout: {exc}"
    except error.URLError as exc:
        return False, {}, (time.perf_counter() - start) * 1000.0, f"url_error: {exc}"
    except Exception as exc:
        return False, {}, (time.perf_counter() - start) * 1000.0, str(exc)


def _bytes_to_gb(num_bytes: float) -> float:
    return round(float(num_bytes) / (1024 ** 3), 3)


def _memory_snapshot() -> Dict[str, Any]:
    if os.name != "nt":
        return {"success": False, "error": "memory snapshot currently supports Windows hosts only"}
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    if not ok:
        return {"success": False, "error": "GlobalMemoryStatusEx failed"}

    used_phys = stat.ullTotalPhys - stat.ullAvailPhys
    used_swap = stat.ullTotalPageFile - stat.ullAvailPageFile
    return {
        "success": True,
        "total_ram_gb": _bytes_to_gb(stat.ullTotalPhys),
        "available_ram_gb": _bytes_to_gb(stat.ullAvailPhys),
        "used_ram_gb": _bytes_to_gb(used_phys),
        "memory_load_percent": int(stat.dwMemoryLoad),
        "total_pagefile_gb": _bytes_to_gb(stat.ullTotalPageFile),
        "used_pagefile_gb": _bytes_to_gb(used_swap),
        "available_pagefile_gb": _bytes_to_gb(stat.ullAvailPageFile),
    }


def _loaded_models() -> List[Dict[str, Any]]:
    ok, data, _, _ = _ollama_call("/api/ps", timeout=10)
    if not ok:
        return []
    models = data.get("models", [])
    return models if isinstance(models, list) else []


def _planner_benchmark(timeout: int = 45) -> Dict[str, Any]:
    prompt = "ping"
    prompt_token_estimate = max(1, len(prompt) // 4)
    start = time.perf_counter()
    try:
        plan = plan_with_qwen(prompt, timeout=timeout)
        duration = round((time.perf_counter() - start) * 1000.0, 2)
        return {
            "success": True,
            "prompt_token_estimate": prompt_token_estimate,
            "inference_duration_ms": duration,
            "timeout_stage": None,
            "likely_cause": "none",
            "plan_tool": plan.get("tool", ""),
        }
    except Exception as exc:
        duration = round((time.perf_counter() - start) * 1000.0, 2)
        text = str(exc).lower()
        timeout_stage = "inference"
        likely = "slow_inference"
        if "timed out" in text:
            timeout_stage = "request_timeout"
            likely = "model_latency_or_overload"
        elif "url_error" in text or "connection" in text:
            timeout_stage = "network"
            likely = "ollama_offline"
        return {
            "success": False,
            "prompt_token_estimate": prompt_token_estimate,
            "inference_duration_ms": duration,
            "timeout_stage": timeout_stage,
            "likely_cause": likely,
            "error": str(exc),
        }


def _recommendations(memory: Dict[str, Any], loaded: List[str], planner: Dict[str, Any]) -> List[str]:
    recs: List[str] = []
    available = float(memory.get("available_ram_gb", 0.0))
    if available and available < SAFE_AVAILABLE_RAM_GB:
        recs.append("Available RAM is below safe threshold. Close memory-heavy apps and browser tabs.")
    if any("llava" in m.lower() for m in loaded) and any("qwen2.5" in m.lower() for m in loaded):
        recs.append("LLaVA + Qwen are loaded together. Unload one model to avoid RAM pressure.")
    if not planner.get("success"):
        if planner.get("likely_cause") == "slow_inference":
            recs.append("Prompt size too large for local inference. Reduce context and tool injection.")
        if planner.get("likely_cause") == "ollama_offline":
            recs.append("Ollama appears offline. Restart Ollama and run recover_ai.")
        if planner.get("likely_cause") == "model_latency_or_overload":
            recs.append("Planner inference is timing out. Unload unused models and reduce concurrent workload.")
    if not recs:
        recs.append("System health is acceptable. Keep only active models loaded.")
    return recs


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()

    if tool == "ollama_status":
        _log("DIAGNOSTICS", "running ollama_status")
        ok_tags, tags, latency, err = _ollama_call("/api/tags", timeout=10)
        ok_ps, ps, ps_latency, ps_err = _ollama_call("/api/ps", timeout=10)
        loaded = ps.get("models", []) if ok_ps and isinstance(ps.get("models"), list) else []
        loaded_names = [str(m.get("name", "")) for m in loaded if isinstance(m, dict)]
        planner_model = DEFAULT_OLLAMA_CONFIG.qwen_model
        missing_planner = planner_model not in [str(m.get("name", "")) for m in tags.get("models", [])] if ok_tags else True
        return structured_result(
            ok_tags,
            tool,
            "Ollama status collected" if ok_tags else f"Ollama status failed: {err}",
            duration=time.perf_counter() - started,
            ollama_online=ok_tags,
            response_ms=round(latency, 2),
            list_models_ms=round(ps_latency, 2),
            models_loaded=len(loaded_names),
            loaded_models=loaded_names,
            planner_model=planner_model,
            active_model=loaded_names[0] if loaded_names else None,
            timeout_detected=("timeout" in err.lower() or "timeout" in ps_err.lower()),
            missing_models=[planner_model] if missing_planner else [],
            errors=[e for e in [err, ps_err] if e],
        )

    if tool == "model_status":
        _log("DIAGNOSTICS", "running model_status")
        ok, tags, latency, err = _ollama_call("/api/tags", timeout=12)
        available = [str(m.get("name", "")) for m in (tags.get("models", []) if ok else []) if isinstance(m, dict)]
        required = [DEFAULT_OLLAMA_CONFIG.qwen_model, DEFAULT_OLLAMA_CONFIG.vision_model]
        missing = [m for m in required if m not in available]
        bench = _planner_benchmark(timeout=45)
        return structured_result(
            ok and not missing,
            tool,
            "Model status checked" if ok else f"Model status failed: {err}",
            duration=time.perf_counter() - started,
            response_ms=round(latency, 2),
            required_models=required,
            available_models=available,
            missing_models=missing,
            planner_benchmark=bench,
            model_load_latency_ms=bench.get("inference_duration_ms"),
        )

    if tool == "memory_status":
        _log("MEMORY", "running memory_status")
        mem = _memory_snapshot()
        mem_success = bool(mem.get("success"))
        mem_payload = {k: v for k, v in mem.items() if k != "success"}
        loaded = [str(m.get("name", "")) for m in _loaded_models()]
        estimated_model_usage_gb = 0.0
        for name in loaded:
            lname = name.lower()
            if "llava" in lname:
                estimated_model_usage_gb += 5.5
            elif "qwen2.5-coder:7b" in lname:
                estimated_model_usage_gb += 4.8
            elif "7b" in lname:
                estimated_model_usage_gb += 4.0
            else:
                estimated_model_usage_gb += 2.0
        warnings: List[str] = []
        if mem.get("success"):
            if mem.get("available_ram_gb", 0) < SAFE_AVAILABLE_RAM_GB:
                warnings.append("Low available RAM")
            if estimated_model_usage_gb > mem.get("available_ram_gb", 0):
                warnings.append("Estimated model usage exceeds available RAM")
        if any("llava" in m.lower() for m in loaded) and any("qwen" in m.lower() for m in loaded):
            warnings.append("LLaVA and Qwen loaded simultaneously")
        return structured_result(
            mem_success,
            tool,
            "Memory status collected" if mem_success else mem.get("error", "Memory status unavailable"),
            duration=time.perf_counter() - started,
            **mem_payload,
            loaded_models=loaded,
            estimated_model_memory_gb=round(estimated_model_usage_gb, 3),
            memory_pressure=bool(warnings),
            warnings=warnings,
        )

    if tool == "cpu_status":
        _log("PERFORMANCE", "running cpu_status")
        import subprocess

        ps_cmd = "(Get-Counter '\\Processor(_Total)\\% Processor Time').CounterSamples.CookedValue"
        completed = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=8)
        cpu_percent = None
        if completed.returncode == 0:
            try:
                cpu_percent = round(float(completed.stdout.strip().splitlines()[-1]), 2)
            except Exception:
                cpu_percent = None
        success = completed.returncode == 0 and cpu_percent is not None
        return structured_result(
            success,
            tool,
            "CPU status collected" if success else "CPU status probe failed",
            duration=time.perf_counter() - started,
            cpu_percent=cpu_percent,
            stderr=completed.stderr[-300:] if completed.stderr else "",
        )

    if tool == "ai_health_check":
        _log("AI HEALTH", "running ai_health_check")
        conn = check_ollama_connection(timeout=8)
        model = execute("model_status", {})
        planner = _planner_benchmark(timeout=30)
        loaded = _loaded_models()
        ai_ok = bool(conn.get("ok")) and bool(model.get("success")) and bool(planner.get("success"))
        return structured_result(
            ai_ok,
            tool,
            "AI health check complete" if ai_ok else "AI health check found failures",
            duration=time.perf_counter() - started,
            ollama_online=bool(conn.get("ok")),
            models_loaded=len(loaded),
            planner_model=DEFAULT_OLLAMA_CONFIG.qwen_model,
            response_ms=planner.get("inference_duration_ms"),
            planner=planner,
            model=model,
            timeout_conditions_detected=not planner.get("success"),
        )

    if tool == "stt_status":
        _log("DIAGNOSTICS", "running stt_status")
        pipeline = get_pipeline()
        if pipeline is None:
            return structured_result(False, tool, "Audio pipeline is not initialized", duration=time.perf_counter() - started)
        diag = pipeline.diagnostics()
        stt = diag.get("stt", {})
        return structured_result(
            bool(stt.get("loaded")),
            tool,
            "STT status collected",
            duration=time.perf_counter() - started,
            listening_active=diag.get("listening_active"),
            queue_health=diag.get("queue_health"),
            latency=diag.get("latency"),
            stt=stt,
            transcription_failures=diag.get("transcription_failures"),
        )

    if tool == "wakeword_status":
        _log("DIAGNOSTICS", "running wakeword_status")
        pipeline = get_pipeline()
        if pipeline is None:
            return structured_result(False, tool, "Audio pipeline is not initialized", duration=time.perf_counter() - started)
        diag = pipeline.diagnostics()
        wake = diag.get("wakeword", {})
        return structured_result(
            bool(wake.get("loaded")),
            tool,
            "Wake word configuration healthy" if wake.get("loaded") else "Wake word model unavailable",
            duration=time.perf_counter() - started,
            wake_word="jarvis",
            listening_active=diag.get("listening_active"),
            wakeword=wake,
            queue_health=diag.get("queue_health"),
            latency=diag.get("latency"),
        )

    if tool == "vad_status":
        _log("DIAGNOSTICS", "running vad_status")
        pipeline = get_pipeline()
        if pipeline is None:
            return structured_result(False, tool, "Audio pipeline is not initialized", duration=time.perf_counter() - started)
        diag = pipeline.diagnostics()
        vad = diag.get("vad", {})
        return structured_result(
            bool(vad.get("loaded")),
            tool,
            "VAD status collected",
            duration=time.perf_counter() - started,
            listening_active=diag.get("listening_active"),
            vad=vad,
            queue_health=diag.get("queue_health"),
        )

    if tool == "microphone_status":
        _log("DIAGNOSTICS", "running microphone_status")
        pipeline = get_pipeline()
        if pipeline is None:
            return structured_result(False, tool, "Audio pipeline is not initialized", duration=time.perf_counter() - started)
        diag = pipeline.diagnostics()
        mic = diag.get("microphone", {})
        return structured_result(
            bool(mic.get("running")),
            tool,
            "Microphone status collected",
            duration=time.perf_counter() - started,
            listening_active=diag.get("listening_active"),
            microphone=mic,
            queue_health=diag.get("queue_health"),
            last_error=diag.get("last_error"),
        )

    if tool == "executor_status":
        _log("DIAGNOSTICS", "running executor_status")
        from tools.executor_router import _DOMAIN_EXECUTORS  # type: ignore

        registered = sorted(_DOMAIN_EXECUTORS.keys())
        required = {"system", "windows", "filesystem", "browser", "productivity", "developer", "ai", "media", "vision", "communication", "diagnostics"}
        missing = sorted(list(required - set(registered)))
        return structured_result(
            not missing,
            tool,
            "Executor routing checked",
            duration=time.perf_counter() - started,
            registered_domains=registered,
            missing_domains=missing,
        )

    if tool == "validator_status":
        _log("DIAGNOSTICS", "running validator_status")
        pass_case = validate_tool_call("open_app", {"app_name": "notepad"})
        fail_case = validate_tool_call("set_volume", {"level": 1000})
        return structured_result(
            pass_case.ok and (not fail_case.ok),
            tool,
            "Validator status checked",
            duration=time.perf_counter() - started,
            passing_case=pass_case.to_dict(),
            failing_case=fail_case.to_dict(),
        )

    if tool == "tool_status":
        _log("DIAGNOSTICS", "running tool_status")
        all_tools = list_tools()
        by_domain: Dict[str, int] = {}
        for spec in all_tools:
            domain = str(spec.get("domain", "unknown"))
            by_domain[domain] = by_domain.get(domain, 0) + 1
        return structured_result(
            True,
            tool,
            "Tool registry status collected",
            duration=time.perf_counter() - started,
            total_tools=len(all_tools),
            tools_by_domain=by_domain,
        )

    if tool == "vision_status":
        _log("DIAGNOSTICS", "running vision_status")
        from tools.executor_router import execute_tool

        probe = execute_tool("analyze_screen", {"prompt": "diagnostics probe"})
        ok = bool(probe.get("success"))
        return structured_result(
            ok,
            tool,
            "Vision diagnostic probe complete" if ok else "Vision provider probe failed",
            duration=time.perf_counter() - started,
            probe=probe,
        )

    if tool == "ocr_status":
        _log("DIAGNOSTICS", "running ocr_status")
        from tools.executor_router import execute_tool

        probe = execute_tool("read_screen_text", {})
        ok = bool(probe.get("success"))
        return structured_result(
            ok,
            tool,
            "OCR diagnostic probe complete" if ok else "OCR provider probe failed",
            duration=time.perf_counter() - started,
            probe=probe,
        )

    if tool == "performance_report" or tool == "run_full_diagnostics":
        _log("PERFORMANCE", "running full performance diagnostics")
        mem = execute("memory_status", {})
        cpu = execute("cpu_status", {})
        ollama = execute("ollama_status", {})
        planner = _planner_benchmark(timeout=40)
        loaded = ollama.get("loaded_models", [])
        failed_tools = []
        for t in ("vision_status", "ocr_status", "ai_health_check"):
            probe = execute(t, {})
            if not probe.get("success"):
                failed_tools.append({"tool": t, "error": probe.get("error", "failed")})
        recommendations = _recommendations(mem, loaded, planner)
        return structured_result(
            True,
            tool,
            "Full diagnostics complete",
            duration=time.perf_counter() - started,
            ram_usage=mem,
            cpu_usage=cpu,
            loaded_models=loaded,
            active_providers={
                "ollama": bool(ollama.get("ollama_online")),
                "vision_provider": "none",
                "ocr_provider": "none",
            },
            planner_latency_ms=planner.get("inference_duration_ms"),
            timeout_history=[planner],
            slowest_tools=[
                {"tool": "planner_benchmark", "duration_ms": planner.get("inference_duration_ms", 0)},
                {"tool": "ollama_status", "duration_ms": ollama.get("response_ms", 0)},
            ],
            failed_tools=failed_tools,
            recommendations=recommendations,
        )

    if tool == "unload_models":
        _log("RECOVERY", "unloading inactive models")
        loaded = _loaded_models()
        unloaded: List[str] = []
        errors: List[str] = []
        for entry in loaded:
            name = str(entry.get("name", ""))
            if not name:
                continue
            ok, _, _, err = _ollama_call("/api/generate", method="POST", payload={"model": name, "prompt": "", "keep_alive": 0, "stream": False}, timeout=20)
            if ok:
                unloaded.append(name)
            else:
                errors.append(f"{name}: {err}")
        return structured_result(
            len(errors) == 0,
            tool,
            "Unload models complete" if not errors else "Unload models completed with errors",
            duration=time.perf_counter() - started,
            unloaded_models=unloaded,
            errors=errors,
        )

    if tool == "reload_models":
        _log("RECOVERY", "reloading planner model")
        warm = warmup_qwen_model(timeout=90)
        ok = bool(warm.get("ok"))
        return structured_result(
            ok,
            tool,
            "Planner model reloaded" if ok else "Planner model reload failed",
            duration=time.perf_counter() - started,
            planner_model=DEFAULT_OLLAMA_CONFIG.qwen_model,
            warmup=warm,
        )

    if tool == "recover_ai":
        _log("RECOVERY", "recover_ai started")
        unload = execute("unload_models", {})
        conn = check_ollama_connection(timeout=8)
        reload = execute("reload_models", {})
        state = _read_state()
        state["safe_mode"] = False
        _write_state(state)
        ok = bool(conn.get("ok")) and bool(reload.get("success"))
        return structured_result(
            ok,
            tool,
            "AI recovery completed" if ok else "AI recovery incomplete",
            duration=time.perf_counter() - started,
            unload=unload,
            ollama_connection=conn,
            reload=reload,
            ai_state_cleared=True,
        )

    if tool == "emergency_safe_mode":
        _log("RECOVERY", "enabling emergency safe mode")
        state = _read_state()
        state["safe_mode"] = True
        state["enabled_at"] = time.time()
        _write_state(state)
        return structured_result(
            True,
            tool,
            "Emergency safe mode enabled",
            duration=time.perf_counter() - started,
            safe_mode=True,
            planner_disabled=True,
            mode="deterministic_only",
        )

    return structured_result(False, tool, "Diagnostics tool not implemented", duration=time.perf_counter() - started)
