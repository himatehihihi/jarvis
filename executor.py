import hands
from tools.executor_router import execute_tool
from tools.retry_manager import RetryManager


class IntentExecutor:
    def __init__(self, speak, handlers=None):
        self.speak = speak
        self.handlers = {}
        self.retry_manager = RetryManager()
        self.register_defaults()
        if handlers:
            self.handlers.update(handlers)

    def register_defaults(self):
        self.handlers.update({
            "open_app": self.open_app,
            "open_known_target": self.open_known_target,
            "open_website": self.open_website,
            "youtube_search": self.youtube_search,
            "play_song": self.play_song,
            "image_search": self.image_search,
            "maps_search": self.maps_search,
            "web_search": self.web_search,
            "type_text": self.type_text,
            "press_key": self.press_key,
            "close_window": self.close_window,
            "switch_window": self.switch_window,
            "whatsapp_message": self.whatsapp_message,
            "whatsapp_call": self.whatsapp_call,
            "whatsapp_video_call": self.whatsapp_video_call,
            "tool_execute": self.tool_execute,
            "multi_step": self.multi_step,
            "unknown": self.unknown,
        })

    def execute(self, intent):
        if not isinstance(intent, dict):
            self.speak("I heard you, but I could not understand that command")
            return False

        handler = self.handlers.get(intent.get("intent"))
        if not handler:
            self.speak("I heard you, but I do not know that command yet")
            return False
        print(f"[DEBUG] selected_handler={intent.get('intent')}")
        return handler(intent)

    def do_action(self, action, intent_name="", payload=None):
        self.speak("Doing it now")
        context = {"intent": intent_name, "payload": payload or {}}
        outcome = self.retry_manager.run_with_retry(context, action)
        if not outcome.success:
            self.speak("That did not work")
        return outcome.final_result if outcome.final_result is not None else outcome.success

    def tool_execute(self, intent):
        tool = str(intent.get("tool", "")).strip()
        params = intent.get("parameters") if isinstance(intent.get("parameters"), dict) else {}
        context = {"intent": "tool_execute", "tool": tool, "payload": {"parameters": params}}
        outcome = self.retry_manager.run_with_retry(context, lambda: execute_tool(tool, params))
        result = outcome.final_result if isinstance(outcome.final_result, dict) else {"success": bool(outcome.success), "tool": tool, "error": "Execution failed after retries"}
        if result.get("success"):
            self.speak(result.get("message", "Done"))
        else:
            self.speak(result.get("error", "Execution failed"))
        if isinstance(result, dict):
            result["retry"] = {
                "attempts": outcome.attempts,
                "failure_class": outcome.failure_class,
                "strategy": outcome.strategy,
                "history": outcome.history,
            }
        return result

    def open_app(self, intent):
        target = intent.get("target", "")
        if self.looks_like_website(target):
            return self.do_action(lambda: hands.open_website(target), "open_website", {"target": target})
        return self.do_action(lambda: hands.open_app(target), "open_app", {"target": target})

    def open_known_target(self, intent):
        target = intent.get("target", "")
        if target == "youtube":
            return self.do_action(hands.open_youtube, "open_known_target", {"target": target})
        if target == "google":
            return self.do_action(hands.open_google, "open_known_target", {"target": target})
        if target == "notepad":
            return self.do_action(hands.open_notepad, "open_known_target", {"target": target})
        if target in ["microsoft to do", "todo", "to do"]:
            return self.do_action(hands.open_microsoft_todo, "open_known_target", {"target": target})
        return self.open_app(intent)

    def open_website(self, intent):
        target = intent.get("target", "")
        return self.do_action(lambda: hands.open_website(target), "open_website", {"target": target})

    def youtube_search(self, intent):
        query = intent.get("query", "")
        return self.do_action(lambda: hands.search_youtube(query), "youtube_search", {"query": query})

    def play_song(self, intent):
        query = intent.get("query", "")
        platform = intent.get("platform", "default")
        print(f"[MEDIA] selected_platform={platform}")
        return self.do_action(lambda: hands.play_song(query, platform), "play_song", {"query": query, "platform": platform})

    def web_search(self, intent):
        query = intent.get("query", "")
        return self.do_action(lambda: hands.search_google(query), "web_search", {"query": query})

    def image_search(self, intent):
        query = intent.get("query", "")
        return self.do_action(lambda: hands.search_google_images(query), "image_search", {"query": query})

    def maps_search(self, intent):
        query = intent.get("query", "")
        return self.do_action(lambda: hands.search_google_maps(query), "maps_search", {"query": query})

    def type_text(self, intent):
        text = intent.get("text", "")
        return self.do_action(lambda: hands.type_in_active_app(text), "type_text", {"text": text})

    def press_key(self, intent):
        key = intent.get("key", "")
        return self.do_action(lambda: hands.press_key_command(key), "press_key", {"key": key})

    def close_window(self, intent):
        return self.do_action(hands.close_active_window, "close_window", {})

    def switch_window(self, intent):
        return self.do_action(hands.switch_window, "switch_window", {})

    def whatsapp_message(self, intent):
        target = intent.get("target", "")
        message = intent.get("message", "")
        return self.do_action(lambda: hands.send_whatsapp_message(target, message), "whatsapp_message", {"target": target, "message": message})

    def whatsapp_call(self, intent):
        target = intent.get("target", "")
        return self.do_action(lambda: hands.call_whatsapp_contact(target), "whatsapp_call", {"target": target})

    def whatsapp_video_call(self, intent):
        target = intent.get("target", "")
        return self.do_action(lambda: hands.call_whatsapp_contact(target, video=True), "whatsapp_video_call", {"target": target})

    def multi_step(self, intent):
        result = True
        for step in intent.get("steps", [])[:4]:
            result = self.execute(step)
            if result == "exit":
                return "exit"
        return result

    def unknown(self, intent):
        self.speak("I heard you, but I do not know that command yet")
        return False

    def looks_like_website(self, target):
        target = str(target).strip().lower()
        return target in hands.SITE_ALIASES or "." in target or " dot " in target
