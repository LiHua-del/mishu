import unittest
import threading
import time
from unittest.mock import patch

import server
from mishu.config import env_float, env_int
from mishu.ai import chat_url, sanitize_result
from mishu.sync import clean_device_id, clean_sync_device_id, normalize_book


class AiBoundaryTests(unittest.TestCase):
    def test_chat_url_accepts_root_v1_and_full_paths(self):
        self.assertEqual(chat_url("https://ai.example.com"), "https://ai.example.com/v1/chat/completions")
        self.assertEqual(chat_url("https://ai.example.com/v1"), "https://ai.example.com/v1/chat/completions")
        self.assertEqual(
            chat_url("https://ai.example.com/v1/chat/completions"),
            "https://ai.example.com/v1/chat/completions",
        )

    def test_ai_result_cannot_insert_unknown_book(self):
        result = sanitize_result(
            {"rankedIds": ["unknown", "book-2"], "reasons": {"unknown": "伪造", "book-2": "匹配"}},
            ["book-1", "book-2"],
        )
        self.assertEqual(result["rankedIds"], ["book-2", "book-1"])
        self.assertEqual(result["reasons"], {"book-2": "匹配"})


class SyncBoundaryTests(unittest.TestCase):
    def test_sync_device_id_rejects_cookie_separator(self):
        self.assertEqual(clean_device_id("device.local-123"), "device.local-123")
        self.assertEqual(clean_sync_device_id("device.local-123"), "")
        self.assertEqual(clean_sync_device_id("device-local-123"), "device-local-123")

    def test_sync_book_is_bounded_and_normalized(self):
        book = normalize_book({
            "id": " book-1 ", "title": " 测试书 ", "author": "", "words": 99_999,
            "genres": ["都市", "都市"], "contentTags": [{"name": "系统", "confidence": 4}],
        })
        self.assertIsNotNone(book)
        self.assertEqual(book["title"], "测试书")
        self.assertEqual(book["genres"], ["都市"])
        self.assertEqual(book["contentTags"][0]["confidence"], 1)
        self.assertEqual(book["words"], 10_000)

    def test_sync_book_ignores_invalid_numeric_values(self):
        book = normalize_book({
            "id": "book-2", "title": "异常数字测试", "words": "not-a-number",
            "contentTags": [{"name": "系统", "confidence": "unknown"}],
        })
        self.assertEqual(book["words"], 0)
        self.assertEqual(book["contentTags"][0]["confidence"], 0)


class RuntimeBoundaryTests(unittest.TestCase):
    def test_invalid_environment_numbers_fall_back_and_clamp(self):
        with patch.dict("os.environ", {"TEST_NUMBER": ""}):
            self.assertEqual(env_int("TEST_NUMBER", 8, 1, 10), 8)
            self.assertEqual(env_float("TEST_NUMBER", 2.5, 1, 5), 2.5)
        with patch.dict("os.environ", {"TEST_NUMBER": "999"}):
            self.assertEqual(env_int("TEST_NUMBER", 8, 1, 10), 10)

    def test_concurrent_page_loads_are_coalesced(self):
        key = "test:singleflight"
        calls = []
        results = []
        server.DISCOVERY_CACHE.pop(key, None)
        server.DISCOVERY_INFLIGHT.pop(key, None)

        def loader():
            calls.append(1)
            time.sleep(0.03)
            return [{"id": "book-1"}]

        def run():
            results.append(server.cached_page(key, loader, (ValueError,)))

        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [[{"id": "book-1"}]] * 4)


if __name__ == "__main__":
    unittest.main()
