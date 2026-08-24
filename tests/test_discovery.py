import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


def candidate(platform: str, index: int) -> dict:
    return {
        "id": f"{platform}-{index}",
        "platform": platform,
        "title": f"测试书 {index}",
        "author": "测试作者",
        "description": "都市无敌流故事，主角一路横推。",
        "url": f"https://example.com/{platform}/{index}",
        "cover": f"https://example.com/{index}.jpg",
        "genres": ["都市"],
        "contentTags": [{"name": "无敌流", "confidence": 0.9, "source": "分类", "evidence": "无敌流"}],
        "words": 40,
        "status": "连载",
        "rank": index + 1,
        "popularityScore": 80 - index,
    }


class ShuqiParserTests(unittest.TestCase):
    def test_store_page_yields_real_candidate(self):
        body = """
        <ul class="store-ul clear"><li>
          <a href="/book/123456.html"><img class="cover" src="//img.example/cover.jpg"><h3>书库测试书</h3></a>
          <p class="store-tag clear"><a>作者：测试作者</a><span>都市脑洞</span></p>
          <a href="/book/123456.html"><p class="store-des">觉醒系统后一路无敌。</p></a>
        </li></ul>
        """
        books = server.parse_shuqi_store(body, "https://ognv.shuqi.com/store?fc=7&wd=12&st=1&page=2")
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["platform"], "书旗")
        self.assertEqual(books[0]["status"], "连载")
        self.assertEqual(books[0]["rank"], 37)
        self.assertTrue(books[0]["cover"].startswith("https://"))

    def test_detail_page_confirms_words_status_and_official_tags(self):
        body = """
        <div class="view"><img src="//img.example/large.jpg"><div class="view-book-info">
          <span class="bname">详情测试书</span><div class="bauthor">作者：<a>测试作者</a></div>
          <div class="tags clear"><li><a>娱乐圈</a></li><li><a>明星</a></li></div>
          <div class="lastchapter clear"><li>娱乐明星</li><li>42.30万字</li><li>连载</li></div>
          <p class="bookDesc"><span data-text="演员参加综艺后爆红。">展开</span></p>
        </div></div>
        """
        details = server.parse_shuqi_detail(body, "https://ognv.shuqi.com/book/123456.html")
        self.assertEqual(details[0]["words"], 42.3)
        self.assertEqual(details[0]["status"], "连载")
        self.assertIn("娱乐圈", details[0]["genres"])
        self.assertIn("明星", details[0]["genres"])


class UnifiedSourceParserTests(unittest.TestCase):
    def test_fanqie_rank_navigation_discovers_both_channels(self):
        body = """
        <a href="/rank/1_2_257"><span>玄幻脑洞</span></a>
        <a href="/rank/1_1_257">玄幻脑洞</a>
        <a href="/rank/0_2_1139">古风世情</a>
        """
        categories = server.parse_fanqie_rank_categories(body)
        self.assertEqual(categories, [("1", "257", "玄幻脑洞"), ("0", "1139", "古风世情")])

    def test_qidian_category_json_keeps_exact_filters_and_cover(self):
        payload = {"data": {"records": [{
            "bid": 123456, "bName": "起点测试书", "bAuth": "作者甲", "cnt": "42.8万字",
            "cat": "都市", "state": "连载", "desc": "重生后进入娱乐圈。",
        }]}}
        books = server.parse_qidian_category_json(payload, "都市", 2, "")
        self.assertEqual(books[0]["words"], 42.8)
        self.assertEqual(books[0]["status"], "连载")
        self.assertEqual(books[0]["rank"], 21)
        self.assertIn("123456", books[0]["cover"])

    def test_fanqie_library_defers_text_to_detail_page(self):
        payload = {"data": {"book_list": [{
            "book_id": "7654321", "thumb_url": "http://img.example/cover.jpg", "creation_status": 0,
        }]}}
        books = server.parse_fanqie_library(payload, "都市脑洞", 1, "0")
        self.assertEqual(books[0]["status"], "完结")
        self.assertEqual(books[0]["genres"], ["都市脑洞"])
        self.assertTrue(books[0]["cover"].startswith("https://"))

    def test_fanqie_hydration_recomputes_content_tags(self):
        raw = candidate("番茄", 1)
        raw["id"] = "fanqie-7654321"
        raw["contentTags"] = [{"name": "无敌流", "confidence": 0.9, "source": "分类", "evidence": "无敌流"}]
        detail = [{
            "id": "fanqie-7654321", "title": "重生测试书", "author": "作者乙",
            "description": "主角重生回到十年前。", "words": 42, "status": "连载", "genres": ["都市", "重生"],
        }]
        with patch.object(server, "cached_discovery_page", return_value=detail):
            hydrated = server.hydrate_fanqie_book(raw)
        self.assertIn("重生", server.content_tag_names(hydrated, strict_only=True))

    def test_fanqie_placeholder_title_is_never_displayable(self):
        raw = candidate("番茄", 1)
        raw["title"] = "番茄小说 7640771121582722110"
        self.assertFalse(server.has_displayable_book_identity(raw))
        self.assertEqual(
            server.select_six_books([raw], [], [], "any", "any", "all", "mixed", set(), {}),
            [],
        )

    def test_fanqie_known_rank_font_decodes_exact_glyphs(self):
        payload = {"rank": {"book_list": [{
            "bookId": "7654322", "thumbUri": "https://img.example/cover.jpg",
            "bookName": "\ue3e9\ue3ea", "author": "\ue3ec", "abstract": "\ue3ea\ue3ed",
            "wordNumber": "420000", "creationStatus": 1, "currentPos": 1,
        }]}}
        body = f"@font-face{{src:url(dc027189e0ba4cd.woff2)}} window.__INITIAL_STATE__={json.dumps(payload, ensure_ascii=False)}"
        books = server.parse_fanqie_rank(body, "https://fanqienovel.com/rank/1_2_261", "都市日常")
        self.assertEqual(books[0]["title"], "在主")
        self.assertNotRegex(books[0]["title"], r"[\ue000-\uf8ff]")
        self.assertTrue(server.has_displayable_book_identity(books[0]))

    def test_fanqie_unknown_font_is_not_guessed(self):
        payload = {"rank": {"book_list": [{
            "bookId": "7654323", "thumbUri": "https://img.example/cover.jpg",
            "bookName": "\ue3e9\ue3ea", "wordNumber": "420000", "currentPos": 1,
        }]}}
        body = f"@font-face{{src:url(changed-font.woff2)}} window.__INITIAL_STATE__={json.dumps(payload, ensure_ascii=False)}"
        book = server.parse_fanqie_rank(body, "https://fanqienovel.com/rank/1_2_261", "都市日常")[0]
        self.assertFalse(server.has_displayable_book_identity(book))

    def test_qq_category_page_uses_real_page_rank(self):
        body = """
        <div class="book-large rank-book"><a title="QQ测试书" href="//book.qq.com/book-detail/60478048">
          <p class="intro">重生后成为演员。</p><p class="other"><a>作者丙</a><a>·都市生活</a>·连载·42.3万字</p>
        </a></div>
        """
        books = server.parse_qq_category(body, "https://book.qq.com/book-cate/20019-0-1-0-2-0-0-3")
        self.assertEqual(books[0]["rank"], 41)
        self.assertEqual(books[0]["words"], 42.3)
        self.assertEqual(books[0]["platform"], "QQ阅读")
        self.assertIn("/cover/48/60478048/", books[0]["cover"])


class SourceConstraintTests(unittest.TestCase):
    def test_same_work_on_multiple_platforms_is_deduplicated(self):
        shuqi = candidate("书旗", 700)
        shuqi["title"] = "同一本书"
        shuqi["author"] = "同一作者"
        qidian = dict(shuqi, id="起点-700", platform="起点", description="更完整的简介", words=88)
        unique = server.unique_book_candidates([shuqi, qidian])
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["platform"], "起点")

    def test_popularity_is_normalized_within_each_platform(self):
        books = [candidate("起点", index) for index in range(4)] + [candidate("番茄", index + 10) for index in range(4)]
        for index, book in enumerate(books[:4]):
            book["popularityScore"] = 95 - index
        for index, book in enumerate(books[4:]):
            book["popularityScore"] = 55 - index
        normalized = server.normalize_popularity_within_platform(books)
        by_platform = {platform: [book for book in normalized if book["platform"] == platform] for platform in ("起点", "番茄")}
        self.assertGreater(by_platform["起点"][0]["normalizedPopularity"], by_platform["起点"][-1]["normalizedPopularity"])
        self.assertGreater(by_platform["番茄"][0]["normalizedPopularity"], by_platform["番茄"][-1]["normalizedPopularity"])
        self.assertGreater(by_platform["番茄"][0]["normalizedPopularity"], 80)

    def test_single_source_can_fill_all_six_slots(self):
        books = [candidate("书旗", index) for index in range(6)]
        selected = server.select_six_books(books, ["都市"], ["无敌流"], "any", "30to50", "all", "random", set(), {})
        self.assertEqual(len(selected), 6)
        self.assertEqual({book["platform"] for book in selected}, {"书旗"})

    def test_final_guard_rejects_mixed_platform_cache(self):
        contaminated = [candidate("书旗", index) for index in range(2)] + [candidate("番茄", index + 10) for index in range(6)]
        with patch.object(server, "cached_discovery_candidates", return_value=contaminated), \
             patch.object(server, "discover_books", return_value=(contaminated, [])), \
             patch.object(server, "cache_discovery_candidates"):
            books, _, metadata = server.build_discovery_batch(
                ["都市"], ["无敌流"], "any", "30to50", "all", "random", [], ["书旗"], True, {},
            )
        self.assertEqual(books, [])
        self.assertFalse(metadata["fallbackUsed"])

    def test_recycled_batch_returns_before_synchronous_live_crawl(self):
        pool = [candidate("书旗", index) for index in range(18)]
        excluded = [book["id"] for book in pool]
        with patch.object(server, "cached_discovery_candidates", return_value=pool), \
             patch.object(server, "discover_books") as live_crawl, \
             patch.object(server, "schedule_discovery_refresh", return_value=True):
            books, _, metadata = server.build_discovery_batch(
                ["都市"], ["无敌流"], "any", "30to50", "all", "popular",
                excluded, ["书旗"], False, {},
            )
        self.assertEqual(len(books), 6)
        self.assertEqual(metadata["recycleLevel"], 1)
        self.assertTrue(metadata["backgroundRefresh"])
        live_crawl.assert_not_called()

    def test_current_batch_is_always_hard_excluded(self):
        pool = [candidate("书旗", index) for index in range(18)]
        current = [book["id"] for book in pool[:6]]
        history = [book["id"] for book in pool]
        with patch.object(server, "cached_discovery_candidates", return_value=pool), \
             patch.object(server, "discover_books") as live_crawl, \
             patch.object(server, "schedule_discovery_refresh", return_value=True):
            books, _, metadata = server.build_discovery_batch(
                ["都市"], ["无敌流"], "any", "30to50", "all", "popular",
                history, ["书旗"], False, {}, current,
            )
        self.assertEqual(len(books), 6)
        self.assertTrue(set(current).isdisjoint(book["id"] for book in books))
        self.assertTrue(set(current).isdisjoint(book["id"] for book in metadata["analysisCandidates"]))
        self.assertEqual(metadata["recycleLevel"], 2)
        live_crawl.assert_not_called()

    def test_identical_current_batch_is_never_returned(self):
        current_books = [candidate("书旗", index) for index in range(6)]
        current = [book["id"] for book in current_books]
        with patch.object(server, "cached_discovery_candidates", return_value=current_books), \
             patch.object(server, "discover_books", return_value=(current_books, [])), \
             patch.object(server, "cache_discovery_candidates"), \
             patch.object(server, "schedule_discovery_refresh", return_value=True):
            books, _, metadata = server.build_discovery_batch(
                ["都市"], ["无敌流"], "any", "30to50", "all", "popular",
                current, ["书旗"], False, {}, current,
            )
        self.assertEqual(books, [])
        self.assertEqual(metadata["freshEligibleCount"], 0)
        self.assertTrue(metadata["backgroundRefresh"])

    def test_three_popular_batches_do_not_overlap_when_pool_is_large_enough(self):
        pool = [candidate("书旗", index) for index in range(18)]
        history: list[str] = []
        current: list[str] = []
        batches: list[set[str]] = []
        with patch.object(server, "cached_discovery_candidates", return_value=pool), \
             patch.object(server, "discover_books") as live_crawl, \
             patch.object(server, "schedule_discovery_refresh", return_value=True):
            for _ in range(3):
                books, _, _ = server.build_discovery_batch(
                    ["都市"], ["无敌流"], "any", "30to50", "all", "popular",
                    history, ["书旗"], False, {}, current,
                )
                batch = {book["id"] for book in books}
                self.assertEqual(len(batch), 6)
                batches.append(batch)
                current = list(batch)
                history.extend(current)
        self.assertTrue(batches[0].isdisjoint(batches[1]))
        self.assertTrue(batches[1].isdisjoint(batches[2]))
        self.assertTrue(batches[0].isdisjoint(batches[2]))
        live_crawl.assert_not_called()

    def test_partial_fresh_candidates_are_used_before_recycling_older_books(self):
        pool = [candidate("书旗", index) for index in range(22)]
        history: list[str] = []
        current: list[str] = []
        batches: list[set[str]] = []
        with patch.object(server, "cached_discovery_candidates", return_value=pool), \
             patch.object(server, "discover_books") as live_crawl, \
             patch.object(server, "schedule_discovery_refresh", return_value=True):
            for _ in range(4):
                books, _, _ = server.build_discovery_batch(
                    ["都市"], ["无敌流"], "any", "30to50", "all", "popular",
                    history, ["书旗"], False, {}, current,
                )
                batch = {book["id"] for book in books}
                batches.append(batch)
                current = list(batch)
                history.extend(current)
        never_shown_before_fourth = {book["id"] for book in pool} - set().union(*batches[:3])
        self.assertTrue(never_shown_before_fourth)
        self.assertTrue(never_shown_before_fourth.issubset(batches[3]))
        self.assertNotEqual(batches[3], batches[0])
        live_crawl.assert_not_called()

    def test_qidian_and_fanqie_hold_four_of_six_slots(self):
        books = []
        for platform in ("起点", "番茄", "书旗", "七猫", "QQ阅读"):
            for index in range(8):
                book = candidate(platform, index + 100)
                book["id"] = f"{platform}-{index}"
                book["author"] = f"{platform}作者{index}"
                book["popularityScore"] = 99 - index
                books.append(book)
        selected = server.select_six_books(
            books, ["都市"], ["无敌流"], "any", "30to50", "all", "popular", set(), {},
        )
        primary_count = sum(book["platform"] in server.PRIMARY_DISCOVERY_PLATFORMS for book in selected)
        self.assertEqual(len(selected), 6)
        self.assertGreaterEqual(primary_count, 4)
        self.assertLessEqual(len(selected) - primary_count, 2)
        self.assertLessEqual(sum(book["platform"] == "七猫" for book in selected), 1)
        self.assertIn("起点", {book["platform"] for book in selected})
        self.assertIn("番茄", {book["platform"] for book in selected})

    def test_qidian_can_carry_primary_share_when_fanqie_has_no_match(self):
        books = [candidate("起点", index) for index in range(8)]
        books.extend(candidate("书旗", index + 20) for index in range(8))
        for index, book in enumerate(books):
            book["author"] = f"作者{index}"
        selected = server.select_six_books(
            books, ["都市"], ["无敌流"], "any", "30to50", "all", "popular", set(), {},
        )
        self.assertEqual(sum(book["platform"] == "起点" for book in selected), 4)

    def test_qimao_is_fallback_when_other_supplements_are_equally_good(self):
        books = []
        for platform in ("起点", "番茄"):
            for index in range(5):
                book = candidate(platform, index + 500)
                book["id"] = f"{platform}-{index + 500}"
                book["author"] = f"{platform}作者{index}"
                books.append(book)
        for platform in ("书旗", "QQ阅读", "七猫"):
            book = candidate(platform, 599)
            book["id"] = f"{platform}-599"
            book["author"] = f"{platform}作者"
            books.append(book)
        selected = server.select_six_books(
            books, ["都市"], ["无敌流"], "any", "30to50", "all", "popular", set(), {},
        )
        supplements = {book["platform"] for book in selected if book["platform"] not in server.PRIMARY_DISCOVERY_PLATFORMS}
        self.assertEqual(supplements, {"书旗", "QQ阅读"})

    def test_qimao_random_or_heat_score_cannot_bypass_fallback_layer(self):
        books = []
        for platform in ("起点", "番茄"):
            for index in range(6):
                item = candidate(platform, index + 700)
                item["author"] = f"{platform}作者{index}"
                books.append(item)
        for platform, heat in (("书旗", 55), ("QQ阅读", 54), ("七猫", 100)):
            item = candidate(platform, 799)
            item["author"] = f"{platform}作者"
            item["popularityScore"] = heat
            books.append(item)
        selected = server.select_six_books(
            books, ["都市"], ["无敌流"], "any", "30to50", "all", "mixed", set(), {},
        )
        supplements = {book["platform"] for book in selected if book["platform"] not in server.PRIMARY_DISCOVERY_PLATFORMS}
        self.assertEqual(supplements, {"书旗", "QQ阅读"})

    def test_qimao_gets_a_low_frequency_slot_across_five_batches(self):
        books = []
        for platform in ("起点", "番茄", "书旗", "QQ阅读", "七猫"):
            for index in range(36):
                item = candidate(platform, index + 900)
                item["id"] = f"{'qimao' if platform == '七猫' else platform}-{index + 900}"
                item["author"] = f"{platform}作者{index}"
                books.append(item)
        excluded: set[str] = set()
        totals = {"书旗": 0, "QQ阅读": 0, "七猫": 0}
        for _ in range(5):
            selected = server.select_six_books(
                books, ["都市"], ["无敌流"], "any", "30to50", "all", "mixed", excluded, {},
            )
            self.assertEqual(len(selected), 6)
            excluded.update(book["id"] for book in selected)
            for book in selected:
                if book["platform"] in totals:
                    totals[book["platform"]] += 1
        self.assertGreaterEqual(totals["七猫"], 1)
        self.assertLess(totals["七猫"], totals["书旗"] + totals["QQ阅读"])


class AudienceTests(unittest.TestCase):
    def test_default_male_rejects_explicit_female_candidate(self):
        male = candidate("番茄", 1)
        male["audience"] = "male"
        female = candidate("番茄", 2)
        female["audience"] = "female"
        selected = server.select_six_books(
            [male, female], ["都市"], ["无敌流"], "any", "30to50", "all",
            "popular", set(), {}, audience="male",
        )
        self.assertEqual([book["id"] for book in selected], [male["id"]])

    def test_fanqie_plan_channel_is_separated(self):
        rng = __import__("random").Random(1)
        male_urls = [url for url, _ in server.fanqie_rank_plans(["都市"], "any", "popular", rng, 8, "male")]
        female_urls = [url for url, _ in server.fanqie_rank_plans(["都市"], "any", "popular", rng, 8, "female")]
        self.assertTrue(male_urls)
        self.assertTrue(female_urls)
        self.assertTrue(all("/rank/1_" in url for url in male_urls))
        self.assertTrue(all("/rank/0_" in url for url in female_urls))

    def test_dynamic_fanqie_catalog_still_hard_separates_channels(self):
        catalog = [("1", str(1000 + index), f"男频{index}") for index in range(20)]
        catalog += [("0", str(2000 + index), f"女频{index}") for index in range(15)]
        rng = __import__("random").Random(2)
        with patch.object(server, "fanqie_rank_categories", return_value=catalog):
            male_urls = [url for url, _ in server.fanqie_rank_plans([], "any", "mixed", rng, 16, "male")]
            female_urls = [url for url, _ in server.fanqie_rank_plans([], "any", "mixed", rng, 16, "female")]
        self.assertEqual(len(male_urls), 16)
        self.assertEqual(len(female_urls), 16)
        self.assertTrue(all("/rank/1_" in url for url in male_urls))
        self.assertTrue(all("/rank/0_" in url for url in female_urls))

    def test_qimao_default_channel_is_separated(self):
        rng = __import__("random").Random(3)
        male_urls = [url for url, _ in server.qimao_store_plans([], "any", "all", "popular", rng, 12, "male")]
        female_urls = [url for url, _ in server.qimao_store_plans([], "any", "all", "popular", rng, 8, "female")]
        self.assertTrue(male_urls)
        self.assertTrue(female_urls)
        self.assertTrue(all(not any(f"a-{category}-" in url for category in server.QIMAO_FEMALE_CATEGORIES) for url in male_urls))
        self.assertTrue(all(any(f"a-{category}-" in url for category in server.QIMAO_FEMALE_CATEGORIES) for url in female_urls))


class TrendSnapshotTests(unittest.TestCase):
    def test_two_daily_snapshots_create_rising_label(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "DB_FILE", Path(directory) / "test.db"):
            server.init_db()
            book = candidate("番茄", 801)
            with server.DB_LOCK:
                connection = server.db_connect()
                try:
                    connection.executemany(
                        "INSERT INTO rank_snapshots(snapshot_day, book_id, platform, audience, category, rank_value, popularity_score, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            ("2026-08-23", book["id"], "番茄", "male", "都市", 18, 70, "2026-08-23T00:00:00+00:00"),
                            ("2026-08-24", book["id"], "番茄", "male", "都市", 8, 82, "2026-08-24T00:00:00+00:00"),
                        ],
                    )
                    connection.commit()
                finally:
                    connection.close()
            enriched = server.attach_trend_metadata([book])[0]
            self.assertEqual(enriched["trendLabel"], "上升 10 位")
            self.assertGreater(enriched["trendScore"], 0)

    def test_old_rank_snapshots_are_pruned_without_touching_current_candidates(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "DB_FILE", Path(directory) / "test.db"):
            server.init_db()
            old_time = (server.datetime.now(server.timezone.utc) - server.timedelta(days=120)).isoformat()
            with server.DB_LOCK, server.db_connect() as connection:
                connection.execute(
                    "INSERT INTO rank_snapshots(snapshot_day, book_id, platform, audience, category, rank_value, popularity_score, captured_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("2000-01-01", "old-book", "番茄", "male", "都市", 1, 90, old_time),
                )
            current = candidate("番茄", 802)
            server.cache_discovery_candidates([current])
            with server.DB_LOCK, server.db_connect() as connection:
                old_count = connection.execute("SELECT COUNT(*) FROM rank_snapshots WHERE book_id = 'old-book'").fetchone()[0]
                current_count = connection.execute("SELECT COUNT(*) FROM discovery_candidates WHERE book_id = ?", (current["id"],)).fetchone()[0]
            self.assertEqual(old_count, 0)
            self.assertEqual(current_count, 1)


class AiCacheRetentionTests(unittest.TestCase):
    def test_ai_cache_removes_expired_rows(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "DB_FILE", Path(directory) / "test.db"):
            server.init_db()
            old_time = (server.datetime.now(server.timezone.utc) - server.timedelta(days=2)).isoformat()
            with server.DB_LOCK, server.db_connect() as connection:
                connection.execute(
                    "INSERT INTO ai_cache(cache_key, payload, model, updated_at) VALUES (?, ?, ?, ?)",
                    ("expired", "{}", "test", old_time),
                )
            server.ai_cache_put("current", {"ok": True}, "test")
            with server.DB_LOCK, server.db_connect() as connection:
                keys = {row[0] for row in connection.execute("SELECT cache_key FROM ai_cache").fetchall()}
            self.assertEqual(keys, {"current"})


class DatabaseMigrationTests(unittest.TestCase):
    def test_legacy_events_table_adds_device_dimension_before_index(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "DB_FILE", Path(directory) / "legacy.db"):
            connection = server.sqlite3.connect(server.DB_FILE)
            try:
                connection.executescript(
                    "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, book_id TEXT NOT NULL, action TEXT NOT NULL, happened_at TEXT NOT NULL, UNIQUE(book_id, action, happened_at));"
                    "INSERT INTO events(book_id, action, happened_at) VALUES ('legacy-book', 'want', '2026-08-20T00:00:00Z');"
                )
                connection.commit()
            finally:
                connection.close()
            server.init_db()
            connection = server.sqlite3.connect(server.DB_FILE)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(events)")}
                row = connection.execute("SELECT device_id, book_id FROM events").fetchone()
                indexes = {row[1] for row in connection.execute("PRAGMA index_list(events)")}
            finally:
                connection.close()
            self.assertIn("device_id", columns)
            self.assertEqual(row, ("legacy", "legacy-book"))
            self.assertIn("idx_events_device_book", indexes)


class AccessProtectionTests(unittest.TestCase):
    def test_session_token_expires_and_valid_signature_is_accepted(self):
        future = int(server.time.time()) + 60
        self.assertTrue(server.valid_session_token(server.session_token(future)))
        self.assertFalse(server.valid_session_token(server.session_token(int(server.time.time()) - 1)))
        self.assertFalse(server.valid_session_token(f"{future}.changed"))

    def test_failed_logins_are_rate_limited(self):
        address = "unit-test-address"
        server.clear_auth_failures(address)
        for _ in range(8):
            server.record_auth_failure(address)
        self.assertFalse(server.auth_attempt_allowed(address))
        server.clear_auth_failures(address)
        self.assertTrue(server.auth_attempt_allowed(address))


class IntelligentMatchingTests(unittest.TestCase):
    def test_star_intent_accepts_verified_entertainment_category(self):
        book = candidate("番茄", 90)
        book["genres"] = ["星光璀璨"]
        book["description"] = "演员参加综艺节目后进入娱乐圈，逐渐成长为实力派艺人。"
        enriched = server.enrich_content(book)
        self.assertTrue(server.genre_matches(enriched, ["都市"]))
        self.assertTrue(server.book_matches_content_filters(enriched, ["都市"], ["明星"], "any", "any", "all"))

    def test_title_only_star_keyword_is_still_not_strict_match(self):
        book = candidate("书旗", 91)
        book["title"] = "超级大明星"
        book["description"] = "普通上班族处理公司日常工作的故事。"
        book["genres"] = ["都市生活"]
        enriched = server.enrich_content(book)
        self.assertFalse(server.book_matches_content_filters(enriched, ["都市"], ["明星"], "any", "any", "all"))

    def test_qidian_subtag_search_expands_to_related_terms(self):
        plans = server.qidian_listing_plans(["都市"], ["明星"], 6)
        urls = [url for url, _ in plans]
        self.assertTrue(any("%E6%98%8E%E6%98%9F" in url for url in urls))
        self.assertTrue(any("%E5%A8%B1%E4%B9%90%E5%9C%88" in url for url in urls))

    def test_small_verified_pool_triggers_background_expansion(self):
        pool = []
        for index in range(12):
            book = candidate("起点", index)
            book["description"] = "演员进入娱乐圈参加综艺，逐渐成为顶流艺人。"
            pool.append(book)
        with patch.object(server, "cached_discovery_candidates", return_value=pool), \
             patch.object(server, "discover_books") as live_crawl, \
             patch.object(server, "schedule_discovery_refresh", return_value=True) as refresh:
            books, _, metadata = server.build_discovery_batch(
                ["都市"], ["明星"], "any", "any", "all", "popular",
                [], ["起点"], False, {}, [],
            )
        self.assertEqual(len(books), 6)
        self.assertTrue(metadata["backgroundRefresh"])
        self.assertEqual(metadata["targetEligibleCount"], server.DISCOVERY_TARGET_ELIGIBLE)
        refresh.assert_called_once()
        live_crawl.assert_not_called()


class PersonalizationModeTests(unittest.TestCase):
    def test_weak_interaction_preference_survives_sanitizing(self):
        self.assertEqual(server.sanitize_preference_weights({"系统": 0.01}), {"系统": 0.01})

    def test_mixed_mode_uses_preferences_much_more_than_random_mode(self):
        book = candidate("起点", 300)
        book["description"] = "演员重生后进入娱乐圈，参加综艺成为明星。"
        book = server.enrich_content(book)
        preferences = {"明星": 12, "娱乐圈": 12, "重生": 8}
        with patch.object(server.random, "SystemRandom") as system_random:
            system_random.return_value.uniform.return_value = 0
            mixed_base = server.candidate_score(book, ["都市"], [], {}, "mixed")
            mixed_preferred = server.candidate_score(book, ["都市"], [], preferences, "mixed")
            random_base = server.candidate_score(book, ["都市"], [], {}, "random")
            random_preferred = server.candidate_score(book, ["都市"], [], preferences, "random")
        self.assertGreater(mixed_preferred, mixed_base)
        self.assertGreater(mixed_preferred - mixed_base, (random_preferred - random_base) * 5)

    def test_negative_preference_lowers_personalized_rank(self):
        book = candidate("起点", 301)
        book["description"] = "医生依靠医术在医院救治病人。"
        book = server.enrich_content(book)
        neutral = server.candidate_score(book, ["都市"], [], {}, "mixed")
        disliked = server.candidate_score(book, ["都市"], [], {"医术": -12}, "mixed")
        self.assertLess(disliked, neutral)


if __name__ == "__main__":
    unittest.main()
