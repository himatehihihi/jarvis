from __future__ import annotations

from typing import Any, Dict

import hands

from ..common import not_implemented, structured_result


def execute(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if tool == "send_whatsapp":
        target = str(params.get("target", "")).strip()
        message = str(params.get("message", "")).strip()
        ok = hands.send_whatsapp_message(target, message)
        return structured_result(ok, tool, "WhatsApp message sent" if ok else "Failed to send WhatsApp message")
    if tool == "whatsapp_call":
        target = str(params.get("target", "")).strip()
        ok = hands.call_whatsapp_contact(target, video=False)
        return structured_result(ok, tool, "WhatsApp call started" if ok else "Failed to start WhatsApp call")
    if tool == "video_call":
        target = str(params.get("target", "")).strip()
        ok = hands.call_whatsapp_contact(target, video=True)
        return structured_result(ok, tool, "Video call started" if ok else "Failed to start video call")
    return not_implemented(tool)
