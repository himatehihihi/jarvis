from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Optional
import os

import numpy as np

from . import AudioConfig


class OpenWakeWordDetector:
    def __init__(self, config: AudioConfig):
        self.config = config
        self.model = None
        self.loaded = False
        self.last_trigger_time = 0.0
        self.wake_detections = 0
        self.last_confidence = 0.0
        self.last_label: Optional[str] = None
        self._boot_error = ""
        self.inference_framework = "onnx"
        self.model_name: Optional[str] = None
        self.model_path: Optional[str] = None
        self.verbose_rejections = os.getenv("JARVIS_WAKEWORD_VERBOSE_REJECTIONS", "0") == "1"

    def load(self) -> bool:
        print(f"[WAKEWORD] inference_framework={self.inference_framework}")
        try:
            import onnxruntime  # noqa: F401
            import openwakeword
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            hint = str(self.config.wakeword_model_hint or "jarvis").strip().lower().replace(" ", "_")
            alias_map = {
                "jarvis": "hey_jarvis",
                "hey_jarvis": "hey_jarvis",
                "alexa": "alexa",
                "mycroft": "hey_mycroft",
                "hey_mycroft": "hey_mycroft",
                "rhasspy": "hey_rhasspy",
                "hey_rhasspy": "hey_rhasspy",
                "timer": "timer",
                "weather": "weather",
            }
            preferred = alias_map.get(hint, "hey_jarvis")

            available_keys = list(openwakeword.MODELS.keys())
            selected_key = preferred if preferred in available_keys else "hey_jarvis"
            selected_file_stub = f"{selected_key}_v0.1"

            # Ensure ONNX model files are present locally.
            model_dir = Path(openwakeword.__file__).resolve().parent / "resources" / "models"
            onnx_path = model_dir / f"{selected_file_stub}.onnx"
            if not onnx_path.exists():
                download_models(model_names=[selected_file_stub], target_directory=str(model_dir))

            if not onnx_path.exists():
                raise FileNotFoundError(f"Wakeword ONNX model not found after download: {onnx_path}")

            self.model_name = selected_key
            self.model_path = str(onnx_path)

            self.model = Model(
                wakeword_models=[self.model_path],
                inference_framework=self.inference_framework,
            )
            self.loaded = True
            self._boot_error = ""
            print("[WAKEWORD] initialized")
            print(f"[WAKEWORD] model_loaded name={self.model_name} path={self.model_path}")
            print("[WAKEWORD] detection_active=true")
            return True
        except Exception as exc:
            self.loaded = False
            self.model_name = None
            self.model_path = None
            self._boot_error = str(exc)
            print(f"[WAKEWORD] initialization_failure error={exc}")
            print("[WAKEWORD] detection_active=false")
            return False

    def _normalize_predictions(self, pred: Dict[str, float]) -> tuple[Optional[str], float]:
        if not pred:
            return None, 0.0
        best_label = None
        best_score = 0.0
        for label, score in pred.items():
            score_f = float(score)
            if score_f > best_score:
                best_label = str(label)
                best_score = score_f
        return best_label, best_score

    def detect(self, frame: np.ndarray, now: float) -> tuple[bool, float]:
        if not self.loaded or self.model is None:
            return False, 0.0
        pcm16 = np.clip(frame, -1.0, 1.0)
        pcm16 = (pcm16 * 32767.0).astype(np.int16)
        raw = self.model.predict(pcm16)
        label, confidence = self._normalize_predictions(raw if isinstance(raw, dict) else {})
        self.last_confidence = confidence
        self.last_label = label

        expected = (self.model_name or "hey_jarvis").lower()
        if not label or expected not in label.lower():
            return False, confidence

        if confidence < self.config.wake_threshold:
            if self.verbose_rejections:
                print(f"[WAKEWORD] rejected confidence={confidence:.3f} threshold={self.config.wake_threshold}")
            return False, confidence

        if (now - self.last_trigger_time) < self.config.wake_cooldown_s:
            print(f"[WAKEWORD] cooldown confidence={confidence:.3f}")
            return False, confidence

        self.last_trigger_time = now
        self.wake_detections += 1
        print(f"[WAKEWORD] detected confidence={confidence:.3f} model={label}")
        return True, confidence

    def health(self) -> dict:
        return {
            "loaded": self.loaded,
            "wake_threshold": self.config.wake_threshold,
            "cooldown_s": self.config.wake_cooldown_s,
            "wake_detections": self.wake_detections,
            "last_confidence": round(self.last_confidence, 4),
            "last_label": self.last_label,
            "model_name": self.model_name,
            "model_path": self.model_path,
            "detection_active": bool(self.loaded),
            "inference_framework": self.inference_framework,
            "boot_error": self._boot_error,
        }
