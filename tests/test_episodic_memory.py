import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import core.memory as memory


class EpisodicMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.episodic_path = os.path.join(self.temp_dir.name, "episodic_memory.json")
        self.episodic_lock = f"{self.episodic_path}.lock"
        self.original_file = memory.EPISODIC_MEMORY_FILE
        self.original_lock = memory.EPISODIC_MEMORY_LOCK_FILE
        memory.EPISODIC_MEMORY_FILE = self.episodic_path
        memory.EPISODIC_MEMORY_LOCK_FILE = self.episodic_lock

    def tearDown(self):
        memory.EPISODIC_MEMORY_FILE = self.original_file
        memory.EPISODIC_MEMORY_LOCK_FILE = self.original_lock
        self.temp_dir.cleanup()

    def test_add_episode_stores_expected_fields(self):
        memory.add_episode("open youtube", {"domain": "browser", "tool": "open_website"}, {"success": True})
        episodes = memory.get_recent_episodes(limit=5)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["user_command"], "open youtube")
        self.assertEqual(episodes[0]["planner_output"]["tool"], "open_website")
        self.assertEqual(episodes[0]["execution_result"]["success"], True)
        self.assertIsNotNone(memory._parse_iso(episodes[0]["timestamp"]))

    def test_episode_trimming_keeps_only_most_recent_fifty(self):
        for index in range(memory.MAX_EPISODES + 5):
            memory.add_episode(
                f"command-{index}",
                {"domain": "system", "tool": f"tool_{index}"},
                {"success": True, "message": f"done-{index}"},
            )
        episodes = memory.get_recent_episodes(limit=100)
        self.assertEqual(len(episodes), memory.MAX_EPISODES)
        self.assertEqual(episodes[0]["user_command"], "command-5")
        self.assertEqual(episodes[-1]["user_command"], "command-54")

    def test_get_recent_episodes_returns_latest_subset(self):
        for index in range(6):
            memory.add_episode(
                f"task-{index}",
                {"domain": "developer", "tool": f"tool_{index}"},
                {"success": bool(index % 2)},
            )
        recent = memory.get_recent_episodes(limit=3)
        self.assertEqual([item["user_command"] for item in recent], ["task-3", "task-4", "task-5"])

    def test_summarize_recent_episodes_is_bounded_and_uses_no_raw_json(self):
        for index in range(6):
            memory.add_episode(
                f"do something number {index}",
                {"domain": "browser", "tool": f"tool_{index}", "parameters": {"query": "x" * 20}},
                {"success": True, "message": "completed successfully"},
            )
        summary = memory.summarize_recent_episodes(limit=5, max_chars=220)
        self.assertTrue(summary)
        self.assertLessEqual(len(summary), 220)
        self.assertNotIn("{", summary)
        self.assertIn("planner=", summary)
        self.assertIn("result=", summary)

    def test_corruption_recovery_replaces_when_backup_succeeds(self):
        with open(self.episodic_path, "w", encoding="utf-8") as file:
            file.write("{bad json")
        episodes = memory.get_recent_episodes(limit=5)
        self.assertEqual(episodes, [])
        backups = [name for name in os.listdir(self.temp_dir.name) if name.startswith("episodic_memory.json.corrupt.")]
        self.assertTrue(backups)
        with open(self.episodic_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        self.assertEqual(data["episodes"], [])

    def test_corruption_recovery_keeps_file_when_backup_fails(self):
        with open(self.episodic_path, "w", encoding="utf-8") as file:
            file.write("{bad json")

        original_replace = os.replace

        def guarded_replace(src, dst):
            if src == self.episodic_path and ".corrupt." in dst:
                raise OSError("backup blocked")
            return original_replace(src, dst)

        with mock.patch("core.memory.os.replace", side_effect=guarded_replace):
            summary = memory.summarize_recent_episodes(limit=5, max_chars=200)
            self.assertEqual(summary, "")

        with open(self.episodic_path, "r", encoding="utf-8") as file:
            self.assertEqual(file.read(), "{bad json")

    def test_normalization_sorts_and_repairs_invalid_episodes(self):
        raw = {
            "episodes": [
                {"user_command": "", "planner_output": {}, "execution_result": {}, "timestamp": "bad"},
                {
                    "user_command": "later",
                    "planner_output": {"tool": "b"},
                    "execution_result": True,
                    "timestamp": (datetime.now() + timedelta(seconds=10)).isoformat(),
                },
                {
                    "user_command": "earlier",
                    "planner_output": {"tool": "a"},
                    "execution_result": False,
                    "timestamp": datetime.now().isoformat(),
                },
            ]
        }
        with open(self.episodic_path, "w", encoding="utf-8") as file:
            json.dump(raw, file)
        episodes = memory.get_recent_episodes(limit=10)
        self.assertEqual([item["user_command"] for item in episodes], ["earlier", "later"])


if __name__ == "__main__":
    unittest.main()
