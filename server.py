#!/usr/bin/env python3
"""觅书的低资源单体服务：静态 PWA + SQLite 事件 API。"""

from __future__ import annotations

import json
import gzip
import base64
import hashlib
import hmac
import html as html_lib
import mimetypes
import os
import re
import sqlite3
import threading
import time
import random
import secrets
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


from mishu.config import *
from mishu import hotlists
from mishu.auth import auth_attempt_allowed, clear_auth_failures, record_auth_failure, session_token, valid_session_token
from mishu.ai import (
    analyze_books as _analyze_books,
    call as _call_ai,
    chat_url as ai_chat_url,
    extract_content as extract_ai_content,
    friendly_error as friendly_ai_error,
    parse_json as parse_ai_json,
    sanitize_result as sanitize_ai_result,
)
from mishu.sync import (
    clean_device_id,
    clean_sync_device_id,
    new_device_secret as new_sync_device_secret,
    new_invite_token as new_sync_invite_token,
    normalize_book as normalize_sync_book,
    secret_hash as _sync_secret_hash,
)
from mishu.time_utils import china_day, utc_now
DB_LOCK = threading.Lock()
SEARCH_SEMAPHORE = threading.BoundedSemaphore(3)
DISCOVERY_CACHE: dict[str, tuple[float, list[dict]]] = {}
DISCOVERY_CACHE_LOCK = threading.Lock()
DISCOVERY_INFLIGHT: dict[str, threading.Event] = {}
DISCOVERY_CACHE_SECONDS = 300
DISCOVERY_FAILURE_CACHE_SECONDS = 20
DISCOVERY_POOL_SECONDS = 60 * 60 * 24
DISCOVERY_POOL_LIMIT = 2200
DISCOVERY_TARGET_ELIGIBLE = 96
DISCOVERY_TARGET_PER_PRIMARY = 24
DISCOVERY_REFRESH_LOCK = threading.Lock()
DISCOVERY_REFRESHING: set[str] = set()
DISCOVERY_REFRESH_QUEUED: set[str] = set()
SOURCE_HEALTH_LOCK = threading.Lock()
SOURCE_HEALTH_CHECKING: set[str] = set()
QIDIAN_SESSION_LOCK = threading.Lock()
QIDIAN_SESSION: tuple[float, str, str] | None = None
FANQIE_CATEGORY_CACHE: tuple[float, list[tuple[str, str, str]]] | None = None




from mishu import database as _database

ClosingConnection = _database.ClosingConnection


def db_connect() -> sqlite3.Connection:
    return _database.connect(DB_FILE, DATA_DIR)


def init_db() -> None:
    _database.initialize(DB_LOCK, db_connect)


def setting_values(keys: tuple[str, ...]) -> dict[str, str]:
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    with DB_LOCK, db_connect() as connection:
        rows = connection.execute(f"SELECT key, value FROM settings WHERE key IN ({placeholders})", keys).fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def save_settings(values: dict[str, str]) -> None:
    with DB_LOCK, db_connect() as connection:
        for key, value in values.items():
            connection.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, utc_now()),
            )


def delete_settings(keys: tuple[str, ...]) -> None:
    if not keys:
        return
    placeholders = ",".join("?" for _ in keys)
    with DB_LOCK, db_connect() as connection:
        connection.execute(f"DELETE FROM settings WHERE key IN ({placeholders})", keys)



def sync_secret_hash(value: str) -> str:
    return _sync_secret_hash(value, MISHU_SESSION_SECRET)


def migrate_legacy_ai_config(device_id: str) -> None:
    """旧版自定义 AI 仅允许被第一个打开设置的设备认领一次，绝不复制到同步设备。"""
    if not device_id:
        return
    with DB_LOCK, db_connect() as connection:
        current = connection.execute("SELECT 1 FROM device_ai_config WHERE device_id = ?", (device_id,)).fetchone()
        if current:
            return
        rows = connection.execute(
            "SELECT key, value FROM settings WHERE key IN ('ai_api_url', 'ai_api_key', 'ai_api_model')"
        ).fetchall()
        values = {str(row["key"]): str(row["value"]) for row in rows}
        if not values:
            return
        connection.execute(
            "INSERT INTO device_ai_config(device_id, api_url, api_key, api_model, updated_at) VALUES (?, ?, ?, ?, ?)",
            (device_id, values.get("ai_api_url", ""), values.get("ai_api_key", ""), values.get("ai_api_model", ""), utc_now()),
        )
        connection.execute("DELETE FROM settings WHERE key IN ('ai_api_url', 'ai_api_key', 'ai_api_model')")


def ai_config(device_id: str = "") -> dict[str, str]:
    device_id = clean_device_id(device_id)
    if device_id:
        migrate_legacy_ai_config(device_id)
    saved: dict[str, str] = {}
    if device_id:
        with DB_LOCK, db_connect() as connection:
            row = connection.execute(
                "SELECT api_url, api_key, api_model FROM device_ai_config WHERE device_id = ?", (device_id,)
            ).fetchone()
        if row:
            saved = {"apiUrl": str(row["api_url"]), "apiKey": str(row["api_key"]), "model": str(row["api_model"])}
    using_saved = bool(saved.get("apiUrl") or saved.get("apiKey") or saved.get("model"))
    return {
        "apiUrl": saved.get("apiUrl", "").strip() or AI_API_URL,
        "apiKey": saved.get("apiKey", "").strip() or AI_API_KEY,
        "model": saved.get("model", "").strip() or AI_API_MODEL,
        "source": "user" if using_saved else ("built-in" if AI_API_URL and AI_API_KEY and AI_API_MODEL else "none"),
    }


def save_device_ai_config(device_id: str, values: dict[str, str]) -> None:
    device_id = clean_device_id(device_id)
    if not device_id:
        raise ValueError("设备标识无效，请刷新页面后重试")
    with DB_LOCK, db_connect() as connection:
        row = connection.execute(
            "SELECT api_url, api_key, api_model FROM device_ai_config WHERE device_id = ?", (device_id,)
        ).fetchone()
        current = dict(row) if row else {}
        connection.execute(
            "INSERT INTO device_ai_config(device_id, api_url, api_key, api_model, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET api_url=excluded.api_url, api_key=excluded.api_key, "
            "api_model=excluded.api_model, updated_at=excluded.updated_at",
            (
                device_id,
                values.get("apiUrl", current.get("api_url", "")),
                values.get("apiKey", current.get("api_key", "")),
                values.get("model", current.get("api_model", "")),
                utc_now(),
            ),
        )


def delete_device_ai_config(device_id: str) -> None:
    device_id = clean_device_id(device_id)
    if not device_id:
        return
    with DB_LOCK, db_connect() as connection:
        connection.execute("DELETE FROM device_ai_config WHERE device_id = ?", (device_id,))


def call_ai(config: dict[str, str], messages: list[dict], max_tokens: int = 1200) -> str:
    return _call_ai(config, messages, max_tokens, timeout=AI_TIMEOUT)


from mishu.sources.common import (
    _nearby_author, _result, absolute_url, as_wan, clean_book_title,
    clean_html_text, json_bytes, parse_platform_html, platform_url,
)


def fetch_platform_page(platform: str, query: str) -> tuple[list[dict], str | None]:
    page_url = platform_url(platform, query)
    request = Request(
        page_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Mishu/0.1; +https://example.invalid/mishu)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.3",
        },
    )
    try:
        with urlopen(request, timeout=SEARCH_TIMEOUT) as response:
            body = response.read(2_000_000)
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
            charset = response.headers.get_content_charset() or "utf-8"
            text = body.decode(charset, errors="replace")
            return parse_platform_html(platform, text, response.geturl()), None
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeError) as error:
        return [], type(error).__name__


def direct_platform_search(query: str, platforms: list[str]) -> list[dict]:
    results: list[dict] = []
    # 顺序请求更克制，也能减少平台把多个同时请求识别为机器人流量。
    for platform in platforms:
        parsed, error = fetch_platform_page(platform, query)
        if parsed:
            results.extend(parsed[:8])
            continue
        message = "平台搜索页未返回可解析的书卡，点击打开平台查看最新结果。"
        if error:
            message = "平台暂时限制了服务端读取，点击打开平台查看最新结果。"
        results.append({
            **_result(platform, f"{platform}实时搜索", platform_url(platform, query), "打开平台查看", message, search_page=True),
            "error": error or "no-rendered-cards",
        })
    return results


def fetch_html(url: str, limit: int = 2_000_000) -> str:
    request = Request(
        url,
        headers={
            # 详情页（尤其书旗）会把移动端 UA 重定向到仅有脚本的壳，
            # 使用普通浏览器 UA 才能取得字数和状态等服务端 HTML。
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0 Safari/537.36 Mishu/0.3",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urlopen(request, timeout=SEARCH_TIMEOUT) as response:
        body = response.read(limit)
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
        charset = response.headers.get_content_charset() or "utf-8"
        return body.decode(charset, errors="replace")


def fetch_json(url: str, referer: str = "") -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0 Safari/537.36 Mishu/0.3",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    with urlopen(request, timeout=SEARCH_TIMEOUT) as response:
        body = response.read(2_000_000)
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
        return json.loads(body.decode(response.headers.get_content_charset() or "utf-8", errors="replace"))



def fetch_qidian_category_json(url: str, referer: str) -> dict:
    """读取起点公开分类接口；CSRF 令牌来自同一官方分类页会话。"""
    global QIDIAN_SESSION
    with QIDIAN_SESSION_LOCK:
        session = QIDIAN_SESSION
        if not session or time.monotonic() - session[0] >= DISCOVERY_CACHE_SECONDS:
            seed_request = Request(referer, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0 Safari/537.36 Mishu/0.3",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            with urlopen(seed_request, timeout=SEARCH_TIMEOUT) as response:
                response.read(1024)
                cookie_parts: list[str] = []
                csrf_token = ""
                for header in response.headers.get_all("Set-Cookie") or []:
                    cookie = header.split(";", 1)[0].strip()
                    if not cookie or "=" not in cookie:
                        continue
                    cookie_parts.append(cookie)
                    if cookie.startswith("_csrfToken="):
                        csrf_token = cookie.split("=", 1)[1]
            if not csrf_token:
                raise ValueError("起点分类会话缺少 CSRF 令牌")
            session = (time.monotonic(), csrf_token, "; ".join(cookie_parts))
            QIDIAN_SESSION = session
    _, csrf_token, cookie_header = session
    target = url + ("&" if "?" in url else "?") + "_csrfToken=" + quote(csrf_token)
    request = Request(target, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0 Safari/537.36 Mishu/0.3",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer,
        "Cookie": cookie_header,
    })
    with urlopen(request, timeout=SEARCH_TIMEOUT) as response:
        body = response.read(2_000_000)
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
        return json.loads(body.decode(response.headers.get_content_charset() or "utf-8", errors="replace"))


from mishu.sources.qidian import parse_qidian_category_json, parse_qidian_detail, parse_qidian_listing, parse_qidian_rank


def hydrate_qidian_book(book: dict) -> dict:
    details = cached_discovery_page(str(book.get("url") or ""), parse_qidian_detail)
    if not details:
        return book
    merged = dict(book)
    detail = details[0]
    original_genres = list(book.get("genres") or [])
    detail_genres = list(detail.get("genres") or [])
    merged.update(detail)
    if not merged.get("description"):
        merged["description"] = book.get("description", "")
    merged["genres"] = list(dict.fromkeys(original_genres + detail_genres))[:6]
    merged.pop("contentTags", None)
    return enrich_content(merged)


from mishu.sources.qq_read import parse_qq_category, parse_qq_rank, qq_cover_url


from mishu.sources.fanqie import (
    decode_fanqie_rank_text, parse_fanqie_detail, parse_fanqie_library,
    parse_fanqie_rank, parse_fanqie_rank_categories, parse_fanqie_recommend,
)


def fanqie_rank_categories() -> list[tuple[str, str, str]]:
    """五分钟缓存一次动态目录；请求失败时由调用方回退到内置映射。"""
    global FANQIE_CATEGORY_CACHE
    with DISCOVERY_CACHE_LOCK:
        if FANQIE_CATEGORY_CACHE and time.monotonic() - FANQIE_CATEGORY_CACHE[0] < DISCOVERY_CACHE_SECONDS:
            return list(FANQIE_CATEGORY_CACHE[1])
    try:
        categories = parse_fanqie_rank_categories(fetch_html("https://fanqienovel.com/rank/1_2_257"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, ValueError):
        categories = []
    if categories:
        with DISCOVERY_CACHE_LOCK:
            FANQIE_CATEGORY_CACHE = (time.monotonic(), list(categories))
    return categories




def hydrate_fanqie_book(book: dict) -> dict:
    book_id = str(book.get("id") or "").removeprefix("fanqie-")
    if not book_id:
        return book
    url = f"https://fanqienovel.com/page/{book_id}"
    details = cached_discovery_page(url, parse_fanqie_detail)
    if not details:
        return book
    merged = dict(book)
    detail = dict(details[0])
    # 番茄偶尔更换站内字体。未知字体下宁可保留榜单已确认字段，也不让详情页乱码覆盖。
    for field in ("title", "author", "description"):
        if re.search(r"[\ue000-\uf8ff]", str(detail.get(field) or "")):
            detail.pop(field, None)
    original_genres = list(book.get("genres") or [])
    detail_genres = list(detail.get("genres") or [])
    merged.update(detail)
    if not merged.get("title"):
        merged["title"] = book.get("title", "")
    if not merged.get("author"):
        merged["author"] = book.get("author", "未知作者")
    if not merged.get("description"):
        merged["description"] = book.get("description", "")
    merged["genres"] = list(dict.fromkeys(original_genres + detail_genres))[:6]
    merged.pop("contentTags", None)
    return enrich_content(merged)


from mishu.sources.qimao import parse_qimao_discovery


from mishu.sources.shuqi import parse_shuqi_detail, parse_shuqi_rank, parse_shuqi_store


def hydrate_shuqi_book(book: dict) -> dict:
    details = cached_discovery_page(str(book.get("url") or ""), parse_shuqi_detail)
    if not details:
        return book
    merged = dict(book)
    detail = {key: value for key, value in details[0].items() if value not in ("", 0, [], None)}
    original_genres = list(book.get("genres") or [])
    detail_genres = list(detail.get("genres") or [])
    merged.update(detail)
    merged["genres"] = list(dict.fromkeys(original_genres + detail_genres))[:12]
    merged.pop("contentTags", None)
    return enrich_content(merged)


def hydrate_books(books: list[dict], hydrator, limit: int = 24) -> list[dict]:
    """并发补齐详情页字段，限制数量避免实时请求拖垮低配置 VPS。"""
    selected = list(books[:limit])
    if len(selected) < 2:
        return [hydrator(book) for book in selected]
    workers = min(4, len(selected))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        hydrated = list(executor.map(hydrator, selected))
    return hydrated + list(books[limit:])


def cached_page(cache_key: str, loader, expected_errors: tuple[type[BaseException], ...]) -> list[dict]:
    """对同一外部页面合并并发请求，并短暂缓存失败，防止来源异常时形成请求风暴。"""
    now_value = time.monotonic()
    with DISCOVERY_CACHE_LOCK:
        cached = DISCOVERY_CACHE.get(cache_key)
        ttl = DISCOVERY_CACHE_SECONDS if cached and cached[1] else DISCOVERY_FAILURE_CACHE_SECONDS
        if cached and now_value - cached[0] < ttl:
            return [dict(book) for book in cached[1]]
        event = DISCOVERY_INFLIGHT.get(cache_key)
        owner = event is None
        if owner:
            event = threading.Event()
            DISCOVERY_INFLIGHT[cache_key] = event
    if not owner:
        event.wait(timeout=SEARCH_TIMEOUT + 5)
        with DISCOVERY_CACHE_LOCK:
            cached = DISCOVERY_CACHE.get(cache_key)
            return [dict(book) for book in cached[1]] if cached else []
    try:
        books = loader()
    except expected_errors:
        books = []
    finally:
        with DISCOVERY_CACHE_LOCK:
            DISCOVERY_CACHE[cache_key] = (time.monotonic(), books if 'books' in locals() else [])
            signal = DISCOVERY_INFLIGHT.pop(cache_key, None)
            if signal:
                signal.set()
    return [dict(book) for book in books]


def cached_discovery_page(url: str, parser) -> list[dict]:
    return cached_page(
        "html:" + url,
        lambda: parser(fetch_html(url), url),
        (HTTPError, URLError, TimeoutError, OSError, UnicodeError, ValueError),
    )


def cached_json_page(url: str, parser, referer: str = "") -> list[dict]:
    return cached_page(
        "json:" + url,
        lambda: parser(fetch_json(url, referer)),
        (HTTPError, URLError, TimeoutError, OSError, UnicodeError, ValueError, json.JSONDecodeError),
    )


def cached_qidian_json_page(url: str, parser, referer: str) -> list[dict]:
    return cached_page(
        "qidian:" + url,
        lambda: parser(fetch_qidian_category_json(url, referer)),
        (HTTPError, URLError, TimeoutError, OSError, UnicodeError, ValueError, json.JSONDecodeError),
    )


def cached_discovery_plans(plans: list[tuple[str, object]]) -> list[dict]:
    """并发读取少量榜单页；最多四路，兼顾实时性和低配 VPS。"""
    if not plans:
        return []

    def load(plan: tuple[str, object]) -> list[dict]:
        url, parser = plan
        return cached_discovery_page(url, parser)

    workers = min(4, len(plans))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pages = list(executor.map(load, plans))
    return [book for page in pages for book in page]


def cached_json_plans(plans: list[tuple[str, object, str]]) -> list[dict]:
    """并发读取公开 JSON 书库；与 HTML 采集共用四路上限和五分钟缓存。"""
    if not plans:
        return []

    def load(plan: tuple[str, object, str]) -> list[dict]:
        url, parser, referer = plan
        return cached_json_page(url, parser, referer)

    workers = min(4, len(plans))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pages = list(executor.map(load, plans))
    return [book for page in pages for book in page]


def cached_qidian_json_plans(plans: list[tuple[str, object, str]]) -> list[dict]:
    if not plans:
        return []

    def load(plan: tuple[str, object, str]) -> list[dict]:
        url, parser, referer = plan
        return cached_qidian_json_page(url, parser, referer)

    workers = min(4, len(plans))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pages = list(executor.map(load, plans))
    return [book for page in pages for book in page]


def source_page_budget(platforms: list[str], strict: bool = False) -> int:
    if len(platforms) <= 1:
        return 12 if strict else 10
    if len(platforms) == 2:
        return 8 if strict else 6
    return 5 if strict else 4


from mishu.sources.plans import (
    fanqie_library_plans, fanqie_rank_plans as _fanqie_rank_plans,
    qidian_listing_plans, qidian_rank_plans, qidian_store_plans, qimao_store_plans,
    qq_category_plans, qq_rank_plans, shuqi_rank_plans, shuqi_store_plans,
)


def fanqie_rank_plans(genres: list[str], words_key: str, mode: str, rng, budget: int, audience: str = "male") -> list[tuple[str, object]]:
    return _fanqie_rank_plans(genres, words_key, mode, rng, budget, audience, fanqie_rank_categories)


def discover_fanqie_rank_pool(
    genres: list[str], words_key: str, status_key: str, mode: str, audience: str = "male", budget: int = 28,
) -> list[dict]:
    """后台遍历更多动态分类榜；榜单已有完整元数据，不逐本请求详情页。"""
    rng = random.SystemRandom()
    books = cached_discovery_plans(fanqie_rank_plans(genres, words_key, mode, rng, budget, audience))
    return [
        enrich_content(book) for book in unique_book_candidates(books)
        if has_displayable_book_identity(book)
        and book_matches_filters(book, genres, words_key, status_key)
        and audience_matches(book, audience)
    ]




from mishu.recommendation.content import canonical_book_key, candidate_identity_quality, unique_book_candidates


from mishu.sources.plans import qimao_discovery_url


from mishu.recommendation.content import (
    audience_matches, book_matches_content_filters, book_matches_filters,
    content_tag_names, content_tags_for, enrich_content, genre_matches,
    has_displayable_book_identity, subtag_match_count, subtags_match,
)


def cache_discovery_candidates(books: list[dict]) -> None:
    if not books:
        return
    fetched_at = utc_now()
    prepared: list[tuple[str, str, str, str]] = []
    snapshots: list[tuple[str, str, str, str, str, int, float, str]] = []
    source_counts: dict[str, int] = {}
    snapshot_day = china_day()
    for raw in books:
        if not isinstance(raw, dict):
            continue
        book = enrich_content(raw)
        book_id = str(book.get("id") or "")[:160]
        platform = clean_html_text(str(book.get("platform") or ""))[:32]
        if not book_id or not platform or not has_displayable_book_identity(book) or not book.get("cover"):
            continue
        prepared.append((book_id, platform, json.dumps(book, ensure_ascii=False, separators=(",", ":")), fetched_at))
        source_counts[platform] = source_counts.get(platform, 0) + 1
        rank_value = max(0, int(book.get("rank") or 0))
        if rank_value:
            category = clean_html_text(str((book.get("genres") or [""])[0]))[:80]
            audience = str(book.get("audience") or "")[:12]
            snapshots.append((
                snapshot_day, book_id, platform, audience, category, rank_value,
                max(0.0, min(100.0, float(book.get("popularityScore") or 0))), fetched_at,
            ))
    if not prepared:
        return
    with DB_LOCK, db_connect() as connection:
        connection.executemany(
            "INSERT INTO discovery_candidates(book_id, platform, payload, fetched_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(book_id) DO UPDATE SET platform=excluded.platform, payload=excluded.payload, fetched_at=excluded.fetched_at",
            prepared,
        )
        if snapshots:
            connection.executemany(
                "INSERT INTO rank_snapshots(snapshot_day, book_id, platform, audience, category, rank_value, popularity_score, captured_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(snapshot_day, book_id, platform, category) DO UPDATE SET "
                "audience=excluded.audience, rank_value=excluded.rank_value, popularity_score=excluded.popularity_score, captured_at=excluded.captured_at",
                snapshots,
            )
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=DISCOVERY_POOL_SECONDS)).isoformat()
        for platform in source_counts:
            count = int(connection.execute(
                "SELECT COUNT(*) FROM discovery_candidates WHERE platform = ? AND fetched_at >= ?", (platform, cutoff),
            ).fetchone()[0])
            connection.execute(
                "INSERT INTO source_health(platform, last_success_at, candidate_count, last_error, last_attempt_at, failure_count, last_check_message) "
                "VALUES (?, ?, ?, '', ?, 0, '采集正常') "
                "ON CONFLICT(platform) DO UPDATE SET last_success_at=excluded.last_success_at, "
                "candidate_count=excluded.candidate_count, last_error='', last_attempt_at=excluded.last_attempt_at, "
                "failure_count=0, last_check_message='采集正常'",
                (platform, fetched_at, count, fetched_at),
            )
        connection.execute(
            "DELETE FROM discovery_candidates WHERE fetched_at < ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=DISCOVERY_POOL_SECONDS)).isoformat(),),
        )
        connection.execute(
            "DELETE FROM discovery_candidates WHERE book_id IN ("
            "SELECT book_id FROM discovery_candidates ORDER BY fetched_at DESC LIMIT -1 OFFSET ?)",
            (DISCOVERY_POOL_LIMIT,),
        )
        connection.execute(
            "DELETE FROM rank_snapshots WHERE captured_at < ?",
            ((datetime.now(timezone.utc) - timedelta(days=RANK_SNAPSHOT_RETENTION_DAYS)).isoformat(),),
        )


def cached_discovery_candidates(platforms: list[str]) -> list[dict]:
    if not platforms:
        return []
    placeholders = ",".join("?" for _ in platforms)
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=DISCOVERY_POOL_SECONDS)).isoformat()
    with DB_LOCK, db_connect() as connection:
        rows = connection.execute(
            f"SELECT payload FROM discovery_candidates WHERE platform IN ({placeholders}) AND fetched_at >= ? "
            "ORDER BY fetched_at DESC LIMIT 1800",
            (*platforms, cutoff),
        ).fetchall()
    books: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload"]))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and has_displayable_book_identity(payload):
            books.append(enrich_content(payload))
    return attach_trend_metadata(unique_book_candidates(books))


def record_source_health_probe(platform: str, candidate_count: int, message: str = "") -> None:
    """记录低频无筛选探测；失败不删除已有候选池，避免一次页面波动破坏推荐。"""
    platform = clean_html_text(platform)[:32]
    if platform not in DISCOVERY_PLATFORMS:
        return
    attempt = utc_now()
    success = candidate_count > 0
    safe_message = clean_html_text(message)[:180]
    with DB_LOCK, db_connect() as connection:
        if success:
            connection.execute(
                "INSERT INTO source_health(platform, last_success_at, candidate_count, last_error, last_attempt_at, failure_count, last_check_message) "
                "VALUES (?, ?, ?, '', ?, 0, ?) "
                "ON CONFLICT(platform) DO UPDATE SET last_success_at=excluded.last_success_at, "
                "candidate_count=MAX(source_health.candidate_count, excluded.candidate_count), last_error='', "
                "last_attempt_at=excluded.last_attempt_at, failure_count=0, last_check_message=excluded.last_check_message",
                (platform, attempt, candidate_count, attempt, safe_message or f"探测正常：获得 {candidate_count} 本候选"),
            )
        else:
            connection.execute(
                "INSERT INTO source_health(platform, last_success_at, candidate_count, last_error, last_attempt_at, failure_count, last_check_message) "
                "VALUES (?, '', 0, ?, ?, 1, ?) "
                "ON CONFLICT(platform) DO UPDATE SET last_error=excluded.last_error, last_attempt_at=excluded.last_attempt_at, "
                "failure_count=source_health.failure_count + 1, last_check_message=excluded.last_check_message",
                (platform, safe_message or "公开页面未取得可解析候选", attempt, safe_message or "探测未获得候选，保留原有候选池"),
            )


def schedule_source_health_check(platforms: list[str] | None = None) -> list[str]:
    """异步探测公开页面结构。每个平台同一时间只检查一次，避免影响用户正常挑书。"""
    requested = [item for item in (platforms or DISCOVERY_PLATFORMS) if item in DISCOVERY_PLATFORMS]
    with SOURCE_HEALTH_LOCK:
        started = [item for item in requested if item not in SOURCE_HEALTH_CHECKING]
        SOURCE_HEALTH_CHECKING.update(started)
    for platform in started:
        def probe(current: str = platform) -> None:
            try:
                books, _ = discover_books([], "any", "all", "popular", set(), [current], audience="all")
                books = [enrich_content(book) for book in books]
                if books:
                    cache_discovery_candidates(books)
                record_source_health_probe(current, len(books))
            except Exception as error:
                record_source_health_probe(current, 0, f"探测异常：{type(error).__name__}")
            finally:
                with SOURCE_HEALTH_LOCK:
                    SOURCE_HEALTH_CHECKING.discard(current)
        threading.Thread(target=probe, name=f"mishu-source-health-{platform}", daemon=True).start()
    return started


def source_health_summary() -> list[dict]:
    """只暴露运行状态，不返回抓取地址、Cookie 或任何密钥。"""
    with DB_LOCK, db_connect() as connection:
        rows = connection.execute(
            "SELECT platform, last_success_at, candidate_count, last_error, last_attempt_at, failure_count, last_check_message "
            "FROM source_health ORDER BY platform"
        ).fetchall()
    by_platform = {str(row["platform"]): row for row in rows}
    output = []
    with SOURCE_HEALTH_LOCK:
        checking = set(SOURCE_HEALTH_CHECKING)
    for platform in DISCOVERY_PLATFORMS:
        row = by_platform.get(platform)
        if not row:
            output.append({
                "platform": platform, "lastSuccessAt": "", "lastAttemptAt": "", "candidateCount": 0,
                "failureCount": 0, "status": "checking" if platform in checking else "unknown",
                "message": "尚未检查公开页面",
            })
            continue
        failures = int(row["failure_count"] or 0)
        status = "checking" if platform in checking else ("ok" if not row["last_error"] else ("warning" if failures < 3 else "risk"))
        output.append({
            "platform": platform,
            "lastSuccessAt": str(row["last_success_at"]),
            "lastAttemptAt": str(row["last_attempt_at"]),
            "candidateCount": int(row["candidate_count"] or 0),
            "failureCount": failures,
            "status": status,
            "message": str(row["last_check_message"] or row["last_error"] or "近期采集正常"),
        })
    return output


def attach_trend_metadata(books: list[dict]) -> list[dict]:
    """把最近两个不同日期的榜单快照变成克制的趋势信号；样本不足时不下结论。"""
    book_ids = list(dict.fromkeys(str(book.get("id") or "") for book in books if book.get("id")))[:800]
    if not book_ids:
        return books
    placeholders = ",".join("?" for _ in book_ids)
    try:
        with DB_LOCK, db_connect() as connection:
            rows = connection.execute(
                f"SELECT book_id, snapshot_day, rank_value, popularity_score FROM rank_snapshots "
                f"WHERE book_id IN ({placeholders}) ORDER BY book_id, snapshot_day DESC, captured_at DESC",
                book_ids,
            ).fetchall()
    except sqlite3.OperationalError:
        # 首次启动或测试替换了空数据库时，趋势属于可选增强，不能拖垮基础推荐。
        return [{**book, "trendScore": 0.0, "trendLabel": "", "rankChange": 0} for book in books]
    history: dict[str, list[sqlite3.Row]] = {}
    seen_days: dict[str, set[str]] = {}
    for row in rows:
        book_id = str(row["book_id"])
        day = str(row["snapshot_day"])
        if day in seen_days.setdefault(book_id, set()) or len(history.setdefault(book_id, [])) >= 2:
            continue
        seen_days[book_id].add(day)
        history[book_id].append(row)
    enriched: list[dict] = []
    for raw in books:
        book = dict(raw)
        recent = history.get(str(book.get("id") or ""), [])
        if len(recent) >= 2:
            latest, previous = recent[0], recent[1]
            rank_change = int(previous["rank_value"] or 0) - int(latest["rank_value"] or 0)
            popularity_change = float(latest["popularity_score"] or 0) - float(previous["popularity_score"] or 0)
            trend_score = max(-12.0, min(12.0, rank_change * 1.4 + popularity_change * 0.18))
            if rank_change >= 3:
                label = f"上升 {rank_change} 位"
            elif rank_change <= -3:
                label = f"回落 {abs(rank_change)} 位"
            elif int(latest["rank_value"] or 999) <= 10:
                label = "稳定热门"
            else:
                label = "榜单稳定"
            book.update({"trendScore": round(trend_score, 2), "trendLabel": label, "rankChange": rank_change})
        else:
            book.update({"trendScore": 0.0, "trendLabel": "", "rankChange": 0})
        enriched.append(book)
    return enriched



from mishu.recommendation.ranking import (
    candidate_score, normalize_popularity_within_platform, prioritize_content_candidates,
    sanitize_preference_weights, select_six_books,
)


def discover_books(
    genres: list[str],
    words_key: str,
    status_key: str,
    mode: str,
    excluded: set[str],
    platforms: list[str],
    subtags: list[str] | None = None,
    subtag_match: str = "any",
    audience: str = "male",
) -> tuple[list[dict], list[str]]:
    rng = random.SystemRandom()
    requested_subtags = list(subtags or [])
    candidates: list[dict] = []
    source_notes: list[str] = []
    if "七猫" in platforms:
        budget = source_page_budget(platforms, words_key != "any" or status_key != "all" or bool(genres))
        books = cached_discovery_plans(qimao_store_plans(genres, words_key, status_key, mode, rng, budget, audience))
        books = prioritize_content_candidates(unique_book_candidates(books, excluded), requested_subtags, subtag_match, mode, rng)
        books = [book for book in books if book_matches_filters(book, genres, words_key, status_key)]
        if books:
            source_notes.append("七猫实时多页书库")
            candidates.extend(books)

    # 书旗以官方书库扩大候选，以榜单补充热度；先按简介/分类安排详情读取顺序。
    if "书旗" in platforms:
        budget = source_page_budget(platforms, words_key != "any" or status_key != "all" or bool(genres))
        store_budget = min(10, max(6, budget))
        rank_budget = min(4, max(2, budget // 3))
        store_books = cached_discovery_plans(shuqi_store_plans(genres, words_key, status_key, mode, rng, store_budget))
        rank_books = cached_discovery_plans(shuqi_rank_plans(words_key, status_key, mode, rng, rank_budget, audience))
        rank_books = [{**book, "audience": audience} for book in rank_books]
        books = [book for book in unique_book_candidates(store_books + rank_books, excluded) if genre_matches(book, genres)]
        books = prioritize_content_candidates(books, requested_subtags, subtag_match, mode, rng)
        hydrate_limit = 64 if len(platforms) == 1 else 32
        books = hydrate_books(books, hydrate_shuqi_book, limit=hydrate_limit)
        books = [book for book in books if book_matches_filters(book, genres, words_key, status_key)]
        if books:
            if store_books:
                source_notes.append("书旗实时书库")
            if rank_books:
                source_notes.append("书旗实时多榜单")
            candidates.extend(books)

    if "起点" in platforms:
        budget = source_page_budget(platforms, words_key != "any" or status_key != "all" or bool(genres))
        store_budget = min(10, max(6, budget))
        rank_budget = min(4, max(2, budget // 3))
        store_books = cached_qidian_json_plans(qidian_store_plans(genres, words_key, status_key, mode, rng, store_budget, audience))
        rank_books = cached_discovery_plans(qidian_rank_plans(genres, words_key, status_key, mode, rng, rank_budget, audience))
        listing_budget = min(7, max(4, budget)) if requested_subtags else max(2, budget // 2)
        listing_books = cached_discovery_plans(qidian_listing_plans(genres, requested_subtags, listing_budget, audience))
        books = store_books + rank_books + listing_books
        books = [{**book, "audience": audience} for book in books]
        books = [book for book in unique_book_candidates(books, excluded) if genre_matches(book, genres)]
        books = prioritize_content_candidates(books, requested_subtags, subtag_match, mode, rng)
        confirmed = [
            book for book in books
            if float(book.get("words") or 0) > 0 and "待核实" not in str(book.get("status") or "") and book.get("description")
        ]
        needs_detail = [book for book in books if book not in confirmed]
        hydrate_limit = 28 if len(platforms) == 1 else 14
        books = confirmed + hydrate_books(needs_detail, hydrate_qidian_book, limit=hydrate_limit)
        books = [book for book in books if book_matches_filters(book, genres, words_key, status_key)]
        if books:
            if store_books:
                source_notes.append("起点实时多页书库")
            if listing_books:
                source_notes.append("起点实时分类与内容检索")
            if rank_books:
                source_notes.append("起点实时多榜单")
            source_notes.append("起点详情确认")
            candidates.extend(books)

    if "QQ阅读" in platforms:
        budget = source_page_budget(platforms, words_key != "any" or status_key != "all" or bool(genres))
        store_budget = 16 if len(platforms) == 1 else min(8, max(6, budget))
        rank_budget = min(4, max(2, budget // 3))
        store_books = cached_discovery_plans(qq_category_plans(genres, words_key, status_key, mode, rng, store_budget))
        rank_books = cached_discovery_plans(qq_rank_plans(genres, words_key, status_key, mode, rng, rank_budget, audience))
        store_books = [{**book, "audience": audience} for book in store_books]
        rank_books = [{**book, "audience": audience} for book in rank_books]
        books = prioritize_content_candidates(unique_book_candidates(store_books + rank_books, excluded), requested_subtags, subtag_match, mode, rng)
        books = [book for book in books if book_matches_filters(book, genres, words_key, status_key)]
        if books:
            if store_books:
                source_notes.append("QQ阅读实时多页书库")
            if rank_books:
                source_notes.append("QQ阅读实时多榜单")
            candidates.extend(books)

    # 番茄书库扩大候选、分类榜提供热度；详情页还原字体并确认简介、字数、状态和标签。
    if "番茄" in platforms:
        budget = source_page_budget(platforms, words_key != "any" or status_key != "all" or bool(genres))
        store_budget = min(10, max(6, budget))
        rank_budget = 16 if len(platforms) == 1 else min(14, max(12, budget * 2))
        store_books = cached_json_plans(fanqie_library_plans(genres, words_key, status_key, mode, rng, store_budget, audience))
        rank_books = cached_discovery_plans(fanqie_rank_plans(genres, words_key, mode, rng, rank_budget, audience))
        # 榜单记录已有真实书名和简介，必须优先于书库占位记录参与跨入口去重。
        rank_books = unique_book_candidates(rank_books, excluded)
        rank_ids = {str(book.get("id") or "") for book in rank_books}
        store_only = [book for book in unique_book_candidates(store_books, excluded) if str(book.get("id") or "") not in rank_ids]
        if audience == "all" and words_key == "any" and status_key == "all":
            for list_type in ("0", "1"):
                suffix = "" if list_type == "0" else "?type=1"
                fanqie_url = "https://fanqienovel.com/api/rank/recommend/list" + suffix
                rank_books.extend(cached_json_page(
                    fanqie_url,
                    lambda payload, selected_type=list_type: parse_fanqie_recommend(payload, selected_type),
                    "https://fanqienovel.com/",
                ))
        rank_books = [book for book in unique_book_candidates(rank_books, excluded) if genre_matches(book, genres)]
        store_only = [book for book in store_only if genre_matches(book, genres)]
        store_only = prioritize_content_candidates(store_only, requested_subtags, subtag_match, mode, rng)
        hydrate_limit = 64 if len(platforms) == 1 else 30
        store_only = hydrate_books(store_only, hydrate_fanqie_book, limit=hydrate_limit)
        books = prioritize_content_candidates(rank_books + store_only, requested_subtags, subtag_match, mode, rng)
        books = [
            book for book in books
            if book_matches_filters(book, genres, words_key, status_key)
            and has_displayable_book_identity(book)
        ]
        if books:
            if store_books:
                source_notes.append("番茄实时多页书库")
            if rank_books:
                source_notes.append("番茄实时分类榜")
            candidates.extend(books)

    unique_books: list[dict] = []
    seen: set[str] = set()
    for book in candidates:
        key = book.get("id", "")
        if not key or key in excluded or key in seen or not book.get("cover"):
            continue
        if not audience_matches(book, audience) or not book_matches_filters(book, genres, words_key, status_key):
            continue
        seen.add(key)
        unique_books.append(book)
    if mode == "random":
        rng.shuffle(unique_books)
    elif mode == "mixed":
        unique_books.sort(key=lambda book: float(book.get("popularityScore", 0)) + rng.uniform(-22, 14), reverse=True)
    else:
        unique_books.sort(key=lambda book: (float(book.get("popularityScore", 0)), -int(book.get("rank", 999))), reverse=True)
    return unique_books[:120], list(dict.fromkeys(source_notes))


def discover_subtag_books(subtags: list[str], words_key: str, status_key: str, mode: str, audience: str = "male") -> list[dict]:
    """细分题材优先读番茄对应分类榜，避免只在大类随机分页里碰运气。"""
    categories: list[tuple[str, str, str]] = []
    for tag in subtags:
        categories.extend(SUBTAG_FANQIE_CATEGORIES.get(tag, ()))
    categories = list(dict.fromkeys(categories))[:8]
    gender_code = "0" if audience == "female" else "1"
    if audience in {"male", "female"}:
        categories = [item for item in categories if item[0] == gender_code]
    if not categories:
        return []
    rank_types = ["1"] if words_key == "under30" else (["2", "1"] if words_key == "any" else ["2"])
    plans: list[tuple[str, object]] = []
    for gender, category_id, label in categories:
        for rank_type in rank_types:
            plans.append((
                f"https://fanqienovel.com/rank/{gender}_{rank_type}_{category_id}",
                lambda body, current_url, category_label=label, selected_gender=gender: [
                    {**book, "audience": "female" if selected_gender == "0" else "male"}
                    for book in parse_fanqie_rank(body, current_url, category_label)
                ],
            ))
    if mode == "random":
        random.SystemRandom().shuffle(plans)
    books = unique_book_candidates(cached_discovery_plans(plans))
    # 分类榜初始数据已经包含封面、简介、字数和状态；避免再用未知字体的详情页覆盖。
    return [
        enrich_content(book) for book in books
        if has_displayable_book_identity(book) and book_matches_filters(book, [], words_key, status_key)
    ]


def schedule_discovery_refresh(
    genres: list[str],
    subtags: list[str],
    subtag_match: str,
    words_key: str,
    status_key: str,
    mode: str,
    platforms: list[str],
    audience: str = "male",
) -> bool:
    """候选轮换时异步扩充池；全局仅允许一个后台采集，适配低配 VPS。"""
    key = json.dumps({
        "genres": genres,
        "subtags": subtags,
        "subtagMatch": subtag_match,
        "words": words_key,
        "status": status_key,
        "platforms": platforms,
        "audience": audience,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with DISCOVERY_REFRESH_LOCK:
        if key in DISCOVERY_REFRESHING or key in DISCOVERY_REFRESH_QUEUED:
            return False
        if DISCOVERY_REFRESHING:
            if len(DISCOVERY_REFRESH_QUEUED) >= 3:
                return False
            DISCOVERY_REFRESH_QUEUED.add(key)

            def wait_for_slot() -> None:
                deadline = time.time() + 120
                while time.time() < deadline:
                    with DISCOVERY_REFRESH_LOCK:
                        ready = not DISCOVERY_REFRESHING
                        if ready:
                            DISCOVERY_REFRESH_QUEUED.discard(key)
                    if ready:
                        schedule_discovery_refresh(
                            genres, subtags, subtag_match, words_key, status_key, mode, platforms, audience,
                        )
                        return
                    time.sleep(0.5)
                with DISCOVERY_REFRESH_LOCK:
                    DISCOVERY_REFRESH_QUEUED.discard(key)

            threading.Thread(target=wait_for_slot, name="mishu-discovery-queued", daemon=True).start()
            return True
        DISCOVERY_REFRESHING.add(key)

    def refresh() -> None:
        try:
            # 热门排序仍在最终选择时生效；采集改用随机页，避免反复刷新同一批榜单。
            refresh_mode = "random" if mode == "popular" else mode
            primary = [platform for platform in platforms if platform in PRIMARY_DISCOVERY_PLATFORMS]
            supplements = [platform for platform in platforms if platform not in PRIMARY_DISCOVERY_PLATFORMS]
            # 主来源先独立扩池，避免被三个补充来源分走采集额度。
            for source_group in (primary, supplements):
                if not source_group:
                    continue
                live_books, _ = discover_books(
                    genres, words_key, status_key, refresh_mode, set(), source_group, subtags, subtag_match, audience,
                )
                cache_discovery_candidates([enrich_content(book) for book in live_books])
            if "番茄" in platforms:
                cache_discovery_candidates(discover_fanqie_rank_pool(
                    genres, words_key, status_key, refresh_mode, audience, budget=28,
                ))
            if subtags and "番茄" in platforms:
                cache_discovery_candidates(discover_subtag_books(subtags, words_key, status_key, refresh_mode, audience))
        except Exception:
            # 后台补充失败不影响已经即时返回给用户的六本。
            pass
        finally:
            with DISCOVERY_REFRESH_LOCK:
                DISCOVERY_REFRESHING.discard(key)

    threading.Thread(target=refresh, name="mishu-discovery-refresh", daemon=True).start()
    return True


def build_discovery_batch(
    genres: list[str],
    subtags: list[str],
    subtag_match: str,
    words_key: str,
    status_key: str,
    mode: str,
    excluded_ids: list[str],
    platforms: list[str],
    allow_fallback: bool,
    preference_weights: dict[str, float],
    current_ids: list[str] | None = None,
    audience: str = "male",
) -> tuple[list[dict], list[str], dict]:
    """组装固定六本：用户选定的平台是硬约束，绝不跨平台静默补足。"""
    # 当前屏幕上的六本始终硬排除；候选不足时只放宽更早的历史，绝不原样返回当前批次。
    current = set(current_ids or [])
    history = list(dict.fromkeys(excluded_ids[-180:]))
    exclusion_sets = [set(history) | current, set(history[-12:]) | current, current]
    source_notes: list[str] = []
    pool = cached_discovery_candidates(platforms)
    source_notes.extend(["近期实时候选池"] if pool else [])

    def choose(current_pool: list[dict]) -> tuple[list[dict], int]:
        # 即使不足六本，也先保留从未展示过的新候选；放宽历史时用较早热门书补齐，
        # 避免候选池被机械切成 A/B/C 三组后整组循环。
        fresh = select_six_books(
            current_pool, genres, subtags, subtag_match, words_key, status_key,
            mode, exclusion_sets[0], preference_weights, audience=audience,
        )
        if len(fresh) == 6:
            return fresh, 0
        fresh_ids = {str(book.get("id") or "") for book in fresh}
        checked: set[frozenset[str]] = set()
        for recycle_level, excluded in enumerate(exclusion_sets[1:], start=1):
            signature = frozenset(excluded)
            if signature in checked:
                continue
            checked.add(signature)
            relaxed = select_six_books(
                current_pool, genres, subtags, subtag_match, words_key, status_key,
                mode, excluded, preference_weights, audience=audience,
            )
            batch = fresh + [book for book in relaxed if str(book.get("id") or "") not in fresh_ids]
            if len(batch) >= 6:
                return batch[:6], recycle_level
        return [], -1

    batch, recycle_level = choose(pool)
    recycled_batch: list[dict] = batch if recycle_level > 0 else []
    recycled_level = recycle_level if recycle_level > 0 else -1
    background_refresh = False
    if recycle_level > 0:
        # 旧逻辑会在这里同步抓完多个平台，连续换批时可能等待几十秒。
        # 先返回可用轮换批次，再单线程后台扩充候选池。
        background_refresh = schedule_discovery_refresh(
            genres, subtags, subtag_match, words_key, status_key, mode, platforms, audience,
        )
    live_sources: list[str] = []
    if len(batch) < 6:
        live_books, live_sources = discover_books(
            genres, words_key, status_key, mode, set(), platforms, subtags, subtag_match, audience,
        )
        live_books = [enrich_content(book) for book in live_books]
        cache_discovery_candidates(live_books)
        live_books = attach_trend_metadata(live_books)
        pool = unique_book_candidates(pool + live_books)
        proposed, level = choose(pool)
        if level == 0:
            batch, recycle_level = proposed, level
        elif proposed and not recycled_batch:
            recycled_batch, recycled_level = proposed, level
        source_notes.extend(live_sources)

    fallback_used = False
    if len(batch) < 6 and subtags and "番茄" in platforms:
        subtag_books = discover_subtag_books(subtags, words_key, status_key, mode, audience)
        cache_discovery_candidates(subtag_books)
        subtag_books = attach_trend_metadata(subtag_books)
        pool = unique_book_candidates(pool + subtag_books)
        proposed, level = choose(pool)
        if level == 0:
            batch, recycle_level = proposed, level
        elif proposed and not recycled_batch:
            recycled_batch, recycled_level = proposed, level
        if subtag_books:
            source_notes.append("番茄细分分类榜")

    if len(batch) < 6 and recycled_batch:
        batch, recycle_level = recycled_batch, recycled_level

    # 双重保险：即使后续逻辑调整，也不能让“换一批”返回与当前完全相同的六本。
    if current and {str(book.get("id") or "") for book in batch} == current:
        batch, recycle_level = [], -1

    if len(batch) < 6 and current and not background_refresh:
        background_refresh = schedule_discovery_refresh(
            genres, subtags, subtag_match, words_key, status_key, mode, platforms, audience,
        )

    # 最后一层来源校验，防止缓存或后续采集逻辑把未选平台混入结果。
    if any(str(book.get("platform") or "") not in platforms for book in batch):
        batch, recycle_level = [], -1

    eligible_count = sum(
        1 for book in unique_book_candidates(pool)
        if has_displayable_book_identity(book)
        and book_matches_content_filters(enrich_content(book), genres, subtags, subtag_match, words_key, status_key)
        and audience_matches(book, audience)
    )
    fresh_eligible_count = sum(
        1 for book in unique_book_candidates(pool, current)
        if has_displayable_book_identity(book)
        and book_matches_content_filters(enrich_content(book), genres, subtags, subtag_match, words_key, status_key)
        and audience_matches(book, audience)
    )
    eligible_by_platform = {
        platform: sum(
            1 for book in unique_book_candidates(pool)
            if str(book.get("platform") or "") == platform
            and has_displayable_book_identity(book)
            and book_matches_content_filters(
                enrich_content(book), genres, subtags, subtag_match, words_key, status_key, audience,
            )
        )
        for platform in platforms
    }

    # 总池保证约 16 批，同时分别维护两个主来源的深度，避免起点单独撑满后番茄不再扩充。
    primary_underfilled = any(
        eligible_by_platform.get(platform, 0) < DISCOVERY_TARGET_PER_PRIMARY
        for platform in platforms if platform in PRIMARY_DISCOVERY_PLATFORMS
    )
    if (eligible_count < DISCOVERY_TARGET_ELIGIBLE or primary_underfilled) and not background_refresh:
        background_refresh = schedule_discovery_refresh(
            genres, subtags, subtag_match, words_key, status_key, mode, platforms, audience,
        )


    analysis_excluded = exclusion_sets[recycle_level] if 0 <= recycle_level < len(exclusion_sets) else current
    analysis_candidates = select_six_books(
        pool, genres, subtags, subtag_match, words_key, status_key, mode, analysis_excluded, preference_weights,
        limit=24, audience=audience,
    )


    metadata = {
        "recycleLevel": recycle_level,
        "backgroundRefresh": background_refresh,
        "fallbackUsed": fallback_used,
        "poolSize": len(pool),
        "eligibleCount": eligible_count,
        "freshEligibleCount": fresh_eligible_count,
        "targetEligibleCount": DISCOVERY_TARGET_ELIGIBLE,
        "targetPerPrimary": DISCOVERY_TARGET_PER_PRIMARY,
        "eligibleByPlatform": eligible_by_platform,
        "audience": audience,
        "analysisCandidates": analysis_candidates,
    }
    return batch if len(batch) == 6 else [], list(dict.fromkeys(source_notes)), metadata


def ai_cache_get(cache_key: str) -> dict | None:
    with DB_LOCK, db_connect() as connection:
        row = connection.execute("SELECT payload, updated_at FROM ai_cache WHERE cache_key = ?", (cache_key,)).fetchone()
    if not row:
        return None
    try:
        updated = datetime.fromisoformat(str(row["updated_at"]))
        if (datetime.now(timezone.utc) - updated).total_seconds() > 1800:
            return None
        payload = json.loads(str(row["payload"]))
        return payload if isinstance(payload, dict) else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def ai_cache_put(cache_key: str, payload: dict, model: str) -> None:
    updated_at = utc_now()
    with DB_LOCK, db_connect() as connection:
        connection.execute(
            "INSERT INTO ai_cache(cache_key, payload, model, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload, model=excluded.model, updated_at=excluded.updated_at",
            (cache_key, json.dumps(payload, ensure_ascii=False), model[:160], updated_at),
        )
        connection.execute(
            "DELETE FROM ai_cache WHERE updated_at < ?",
            ((datetime.now(timezone.utc) - timedelta(hours=AI_CACHE_RETENTION_HOURS)).isoformat(),),
        )
        connection.execute(
            "DELETE FROM ai_cache WHERE cache_key IN ("
            "SELECT cache_key FROM ai_cache ORDER BY updated_at DESC LIMIT -1 OFFSET ?)",
            (AI_CACHE_LIMIT,),
        )


def ai_analyze_books(books: list[dict], preferences: dict, mode: str, config: dict[str, str]) -> tuple[dict, bool]:
    return _analyze_books(
        books,
        preferences,
        mode,
        config,
        cache_get=ai_cache_get,
        cache_put=ai_cache_put,
        ai_call=call_ai,
    )


def brave_platform_search(query: str, platforms: list[str]) -> tuple[list[dict], str | None]:
    results: list[dict] = []
    for platform in platforms:
        search_query = f"site:{PLATFORM_SEARCH[platform]['domain']} {query}"
        params = urlencode({
            "q": search_query,
            "count": "8",
            "country": SEARCH_COUNTRY,
            "search_lang": SEARCH_LANG,
            "safesearch": "moderate",
            "text_decorations": "0",
        })
        request = Request(
            f"https://api.search.brave.com/res/v1/web/search?{params}",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "Cache-Control": "no-cache",
                "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
            },
        )
        try:
            with urlopen(request, timeout=SEARCH_TIMEOUT) as response:
                body = response.read(1_500_000)
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    body = gzip.decompress(body)
                payload = json.loads(body.decode("utf-8", errors="replace"))
            for item in (payload.get("web", {}) or {}).get("results", [])[:8]:
                if not isinstance(item, dict) or not item.get("url") or not item.get("title"):
                    continue
                thumbnail = item.get("thumbnail")
                cover = thumbnail.get("src", "") if isinstance(thumbnail, dict) else str(thumbnail or "")
                results.append(_result(
                    platform,
                    str(item.get("title", "")),
                    str(item.get("url", "")),
                    "平台网页",
                    str(item.get("description", "")),
                    cover=cover,
                ))
        except HTTPError as error:
            if error.code in (401, 403):
                return [], "invalid-api-key"
            if error.code == 429:
                return [], "rate-limited"
            return [], f"http-{error.code}"
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return [], "search-api-unavailable"
    return results, None


class Handler(BaseHTTPRequestHandler):
    server_version = "Mishu/0.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(65)
        self._response_started = False

    def send_response(self, code: int, message: str | None = None) -> None:
        self._response_started = True
        super().send_response(code, message)

    def log_message(self, fmt: str, *args: object) -> None:
        # 保留简洁访问日志，避免把个人书名或请求体写入日志。
        message = fmt % args
        message = re.sub(r"(/api/[^\s?]+)\?[^ ]+", r"\1?[已隐藏]", message)
        print(f"{self.address_string()} - {message}")

    def send_json(self, payload: object, status: int = HTTPStatus.OK, extra_headers: dict[str, str] | None = None) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'")

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 512_000:
                return {}
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def authenticated(self) -> bool:
        if not MISHU_ACCESS_CODE:
            return True
        cookies = self.headers.get("Cookie", "")
        for item in cookies.split(";"):
            name, separator, value = item.strip().partition("=")
            if separator and name == "mishu_session" and valid_session_token(value):
                return True
        return False

    def require_auth(self) -> bool:
        if self.authenticated():
            return True
        self.send_json({"ok": False, "code": "authentication_required", "message": "请输入觅书访问口令。"}, HTTPStatus.UNAUTHORIZED)
        return False

    def auth_cookie(self, value: str, max_age: int) -> str:
        return self.cookie_header("mishu_session", value, max_age)

    def cookie_value(self, name: str) -> str:
        for item in self.headers.get("Cookie", "").split(";"):
            cookie_name, separator, value = item.strip().partition("=")
            if separator and cookie_name == name:
                return value
        return ""

    def cookie_header(self, name: str, value: str, max_age: int) -> str:
        secure = self.headers.get("X-Forwarded-Proto", "").lower() == "https" or os.environ.get("MISHU_COOKIE_SECURE") == "1"
        suffix = "; Secure" if secure else ""
        return f"{name}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{suffix}"

    def sync_cookie(self, space_id: str, device_id: str, device_secret: str, max_age: int = MISHU_SYNC_DAYS * 86400) -> str:
        return self.cookie_header("mishu_sync", f"{space_id}.{device_id}.{device_secret}", max_age)

    def sync_identity(self) -> dict[str, str] | None:
        raw = self.cookie_value("mishu_sync")
        try:
            space_id, device_id, device_secret = raw.split(".", 2)
        except ValueError:
            return None
        if not re.fullmatch(r"[0-9a-f]{32}", space_id) or not clean_sync_device_id(device_id) or len(device_secret) < 24:
            return None
        with DB_LOCK, db_connect() as connection:
            row = connection.execute(
                "SELECT d.device_secret_hash, d.device_name, d.revoked_at FROM sync_devices d "
                "JOIN sync_spaces s ON s.space_id = d.space_id "
                "WHERE d.space_id = ? AND d.device_id = ? AND s.active = 1",
                (space_id, device_id),
            ).fetchone()
            if not row or row["revoked_at"] or not hmac.compare_digest(str(row["device_secret_hash"]), sync_secret_hash(device_secret)):
                return None
            connection.execute(
                "UPDATE sync_devices SET last_seen_at = ? WHERE space_id = ? AND device_id = ?",
                (utc_now(), space_id, device_id),
            )
        return {"spaceId": space_id, "deviceId": device_id, "deviceName": str(row["device_name"] or "")}

    def sync_status_payload(self, identity: dict[str, str] | None = None) -> dict:
        identity = identity or self.sync_identity()
        if not identity:
            return {"connected": False}
        with DB_LOCK, db_connect() as connection:
            row = connection.execute(
                "SELECT joined_at, last_seen_at FROM sync_devices WHERE space_id = ? AND device_id = ?",
                (identity["spaceId"], identity["deviceId"]),
            ).fetchone()
            event_count = int(connection.execute(
                "SELECT COUNT(*) FROM sync_events WHERE space_id = ?", (identity["spaceId"],)
            ).fetchone()[0])
            device_count = int(connection.execute(
                "SELECT COUNT(*) FROM sync_devices WHERE space_id = ? AND revoked_at = ''", (identity["spaceId"],)
            ).fetchone()[0])
        return {
            "connected": True,
            "deviceName": identity["deviceName"] or "这台设备",
            "joinedAt": str(row["joined_at"]) if row else "",
            "lastSeenAt": str(row["last_seen_at"]) if row else "",
            "eventCount": event_count,
            "deviceCount": device_count,
        }

    def sync_create_or_rotate_token(self, payload: dict) -> None:
        device_id = clean_sync_device_id(payload.get("deviceId"))
        device_name = clean_html_text(str(payload.get("deviceName") or "这台设备"))[:40] or "这台设备"
        if not device_id:
            self.send_json({"ok": False, "message": "设备标识无效，请刷新页面后重试。"}, HTTPStatus.BAD_REQUEST)
            return
        identity = self.sync_identity()
        invite_token = new_sync_invite_token()
        now_value = utc_now()
        device_secret = ""
        with DB_LOCK, db_connect() as connection:
            if identity:
                space_id = identity["spaceId"]
                connection.execute(
                    "UPDATE sync_spaces SET invite_hash = ?, rotated_at = ?, active = 1 WHERE space_id = ?",
                    (sync_secret_hash(invite_token), now_value, space_id),
                )
                connection.execute(
                    "UPDATE sync_devices SET device_name = ?, last_seen_at = ? WHERE space_id = ? AND device_id = ?",
                    (device_name, now_value, space_id, identity["deviceId"]),
                )
                device_id = identity["deviceId"]
            else:
                previous = connection.execute(
                    "SELECT d.space_id FROM sync_devices d JOIN sync_spaces s ON s.space_id = d.space_id "
                    "WHERE d.device_id = ? AND d.revoked_at = '' AND s.active = 1 ORDER BY d.joined_at DESC LIMIT 1",
                    (device_id,),
                ).fetchone()
                if previous:
                    space_id = str(previous["space_id"])
                    device_secret = new_sync_device_secret()
                    connection.execute(
                        "UPDATE sync_spaces SET invite_hash = ?, rotated_at = ? WHERE space_id = ?",
                        (sync_secret_hash(invite_token), now_value, space_id),
                    )
                    connection.execute(
                        "UPDATE sync_devices SET device_secret_hash = ?, device_name = ?, last_seen_at = ? "
                        "WHERE space_id = ? AND device_id = ?",
                        (sync_secret_hash(device_secret), device_name, now_value, space_id, device_id),
                    )
                else:
                    space_id = secrets.token_hex(16)
                    device_secret = new_sync_device_secret()
                    connection.execute(
                        "INSERT INTO sync_spaces(space_id, invite_hash, active, created_at, rotated_at) VALUES (?, ?, 1, ?, ?)",
                        (space_id, sync_secret_hash(invite_token), now_value, now_value),
                    )
                    connection.execute(
                        "INSERT INTO sync_devices(space_id, device_id, device_secret_hash, device_name, joined_at, last_seen_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (space_id, device_id, sync_secret_hash(device_secret), device_name, now_value, now_value),
                    )
        headers = None
        if device_secret:
            headers = {"Set-Cookie": self.sync_cookie(space_id, device_id, device_secret)}
        self.send_json({
            "ok": True,
            "token": invite_token,
            "message": "同步令牌仅显示一次，请复制到新设备使用。刷新后旧令牌将不能连接新设备。",
            "status": self.sync_status_payload(identity or {"spaceId": space_id, "deviceId": device_id, "deviceName": device_name}),
        }, extra_headers=headers)

    def sync_join(self, payload: dict) -> None:
        device_id = clean_sync_device_id(payload.get("deviceId"))
        device_name = clean_html_text(str(payload.get("deviceName") or "这台设备"))[:40] or "这台设备"
        invite_token = str(payload.get("token") or "").strip()
        if not device_id or len(invite_token) < 28 or len(invite_token) > 180:
            self.send_json({"ok": False, "message": "同步令牌或设备标识无效。"}, HTTPStatus.BAD_REQUEST)
            return
        now_value = utc_now()
        device_secret = new_sync_device_secret()
        with DB_LOCK, db_connect() as connection:
            space = connection.execute(
                "SELECT space_id FROM sync_spaces WHERE invite_hash = ? AND active = 1",
                (sync_secret_hash(invite_token),),
            ).fetchone()
            if not space:
                self.send_json({"ok": False, "message": "同步令牌已失效或不正确，请在原设备刷新后重试。"}, HTTPStatus.UNAUTHORIZED)
                return
            space_id = str(space["space_id"])
            current = connection.execute(
                "SELECT space_id FROM sync_devices WHERE device_id = ? AND revoked_at = '' ORDER BY joined_at DESC LIMIT 1",
                (device_id,),
            ).fetchone()
            if current and str(current["space_id"]) != space_id:
                self.send_json({"ok": False, "message": "这台设备已连接其他同步空间，请先断开后再连接。"}, HTTPStatus.CONFLICT)
                return
            connection.execute(
                "INSERT INTO sync_devices(space_id, device_id, device_secret_hash, device_name, joined_at, last_seen_at, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, '') ON CONFLICT(space_id, device_id) DO UPDATE SET "
                "device_secret_hash=excluded.device_secret_hash, device_name=excluded.device_name, last_seen_at=excluded.last_seen_at, revoked_at=''",
                (space_id, device_id, sync_secret_hash(device_secret), device_name, now_value, now_value),
            )
        identity = {"spaceId": space_id, "deviceId": device_id, "deviceName": device_name}
        self.send_json(
            {"ok": True, "message": "已连接，正在合并书单与口味记录。", "status": self.sync_status_payload(identity)},
            extra_headers={"Set-Cookie": self.sync_cookie(space_id, device_id, device_secret)},
        )

    def sync_push(self, payload: dict) -> None:
        identity = self.sync_identity()
        if not identity:
            self.send_json({"ok": False, "code": "sync_not_connected", "message": "请先连接同步令牌。"}, HTTPStatus.UNAUTHORIZED)
            return
        raw_events = payload.get("events") if isinstance(payload.get("events"), list) else []
        raw_books = payload.get("books") if isinstance(payload.get("books"), list) else []
        accepted = 0
        now_value = utc_now()
        books = [book for book in (normalize_sync_book(item) for item in raw_books[:180]) if book]
        with DB_LOCK, db_connect() as connection:
            for book in books:
                connection.execute(
                    "INSERT INTO sync_books(space_id, book_id, payload, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(space_id, book_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                    (identity["spaceId"], book["id"], json.dumps(book, ensure_ascii=False, separators=(",", ":")), now_value),
                )
            for event in raw_events[:180]:
                if not isinstance(event, dict):
                    continue
                event_id = str(event.get("eventId") or "").strip()[:100]
                book_id = clean_html_text(str(event.get("bookId") or ""))[:160]
                action = str(event.get("action") or "").strip()[:40]
                happened_at = str(event.get("timestamp") or "").strip()[:80] or now_value
                if not re.fullmatch(r"[A-Za-z0-9._:-]{12,100}", event_id) or not book_id or action not in SYNC_ACTIONS:
                    continue
                extra = {}
                if action == "dislike_reason":
                    reason = clean_html_text(str(event.get("reason") or ""))[:20]
                    if reason:
                        extra["reason"] = reason
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO sync_events(space_id, event_id, device_id, book_id, action, happened_at, received_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (identity["spaceId"], event_id, identity["deviceId"], book_id, action, happened_at, now_value, json.dumps(extra, ensure_ascii=False)),
                )
                accepted += int(cursor.rowcount > 0)
            latest = int(connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM sync_events WHERE space_id = ?", (identity["spaceId"],)
            ).fetchone()[0])
        self.send_json({"ok": True, "accepted": accepted, "cursor": latest})

    def sync_pull(self, payload: dict) -> None:
        identity = self.sync_identity()
        if not identity:
            self.send_json({"ok": False, "code": "sync_not_connected", "message": "请先连接同步令牌。"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            cursor = max(0, int(payload.get("cursor") or 0))
        except (TypeError, ValueError):
            cursor = 0
        with DB_LOCK, db_connect() as connection:
            rows = connection.execute(
                "SELECT sequence, event_id, book_id, action, happened_at, received_at, payload FROM sync_events "
                "WHERE space_id = ? AND sequence > ? ORDER BY sequence ASC LIMIT 301",
                (identity["spaceId"], cursor),
            ).fetchall()
            visible = rows[:300]
            book_ids = list(dict.fromkeys(str(row["book_id"]) for row in visible))
            books = []
            if book_ids:
                placeholders = ",".join("?" for _ in book_ids)
                book_rows = connection.execute(
                    f"SELECT payload FROM sync_books WHERE space_id = ? AND book_id IN ({placeholders})",
                    (identity["spaceId"], *book_ids),
                ).fetchall()
                for row in book_rows:
                    try:
                        value = json.loads(str(row["payload"]))
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if isinstance(value, dict):
                        books.append(value)
        events = []
        for row in visible:
            try:
                extra = json.loads(str(row["payload"]))
            except (TypeError, json.JSONDecodeError):
                extra = {}
            event = {
                "eventId": str(row["event_id"]), "bookId": str(row["book_id"]), "action": str(row["action"]),
                "timestamp": str(row["happened_at"]), "receivedAt": str(row["received_at"]), "sequence": int(row["sequence"]),
            }
            if isinstance(extra, dict):
                event.update({"reason": str(extra["reason"])} if extra.get("reason") else {})
            events.append(event)
        next_cursor = int(visible[-1]["sequence"]) if visible else cursor
        self.send_json({"ok": True, "events": events, "books": books, "nextCursor": next_cursor, "hasMore": len(rows) > len(visible)})

    def sync_disconnect(self) -> None:
        identity = self.sync_identity()
        if identity:
            with DB_LOCK, db_connect() as connection:
                connection.execute(
                    "UPDATE sync_devices SET revoked_at = ? WHERE space_id = ? AND device_id = ?",
                    (utc_now(), identity["spaceId"], identity["deviceId"]),
                )
        self.send_json({"ok": True}, extra_headers={"Set-Cookie": self.cookie_header("mishu_sync", "", 0)})

    def sync_reset(self) -> None:
        identity = self.sync_identity()
        if not identity:
            self.send_json({"ok": False, "message": "当前设备未连接同步。"}, HTTPStatus.BAD_REQUEST)
            return
        with DB_LOCK, db_connect() as connection:
            connection.execute("UPDATE sync_spaces SET active = 0 WHERE space_id = ?", (identity["spaceId"],))
            connection.execute("UPDATE sync_devices SET revoked_at = ? WHERE space_id = ?", (utc_now(), identity["spaceId"]))
        self.send_json({"ok": True}, extra_headers={"Set-Cookie": self.cookie_header("mishu_sync", "", 0)})

    def safe_dispatch(self, callback) -> None:
        try:
            callback()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception as error:
            # 不把堆栈、路径或密钥返回给客户端；日志只记录异常类型。
            print(f"请求处理异常：{type(error).__name__}")
            if self._response_started:
                return
            try:
                self.send_json({"ok": False, "code": "internal_error", "message": "服务暂时不可用，请稍后重试。"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    def do_GET(self) -> None:
        self.safe_dispatch(self._do_GET)

    def _do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self.send_json({"ok": True, "service": "mishu", "time": utc_now()})
            return
        if path == "/api/auth/status":
            self.send_json({"ok": True, "required": bool(MISHU_ACCESS_CODE), "authenticated": self.authenticated()})
            return
        if path.startswith("/api/") and not self.require_auth():
            return
        if path == "/api/hotlists":
            params = parse_qs(parsed.query)
            board_id = (params.get("board") or [""])[0]
            if not board_id:
                self.send_json({"ok": True, "boards": hotlists.CATALOG})
                return
            try:
                self.send_json(hotlists.view(board_id, int((params.get("days") or ["0"])[0])))
            except ValueError as error:
                self.send_json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/books":
            self.send_json({"ok": False, "code": "local_catalog_disabled", "message": "觅书不提供内置书库，请使用实时平台搜索。"}, HTTPStatus.GONE)
            return
        if path == "/api/search":
            self.search_endpoint(urlparse(self.path).query)
            return
        if path == "/api/discover":
            self.discover_endpoint(urlparse(self.path).query)
            return
        if path == "/api/profile":
            device_id = str((parse_qs(parsed.query).get("deviceId") or [""])[0]).strip()[:120]
            self.send_json(self.profile(device_id))
            return
        if path == "/api/source-health":
            self.send_json({"ok": True, "sources": source_health_summary()})
            return
        if path == "/api/sync/status":
            self.send_json({"ok": True, **self.sync_status_payload()})
            return
        if path == "/api/ai/status":
            device_id = clean_device_id((parse_qs(parsed.query).get("deviceId") or [""])[0])
            config = ai_config(device_id)
            enabled = bool(config.get("apiUrl") and config.get("apiKey") and config.get("model"))
            self.send_json({
                "ok": True,
                "enabled": enabled,
                "mode": "external-api" if enabled else "local-only",
                "model": config.get("model", "") if enabled else "",
                "source": config.get("source", "none"),
            })
            return
        if path == "/api/ai/config":
            device_id = clean_device_id((parse_qs(parsed.query).get("deviceId") or [""])[0])
            config = ai_config(device_id)
            self.send_json({
                "ok": True,
                "apiUrl": config.get("apiUrl", ""),
                "model": config.get("model", ""),
                "hasKey": bool(config.get("apiKey")),
                "enabled": bool(config.get("apiUrl") and config.get("apiKey") and config.get("model")),
                "source": config.get("source", "none"),
            })
            return
        if path == "/api/backup":
            device_id = clean_device_id((parse_qs(parsed.query).get("deviceId") or [""])[0])
            self.send_json(self.backup(device_id))
            return
        self.serve_static(path)

    def search_endpoint(self, query_string: str) -> None:
        if not SEARCH_SEMAPHORE.acquire(blocking=False):
            self.send_json({"ok": False, "code": "search_busy", "message": "当前搜索请求较多，请稍后再试。"}, HTTPStatus.TOO_MANY_REQUESTS)
            return
        try:
            self._search_endpoint(query_string)
        finally:
            SEARCH_SEMAPHORE.release()

    def discover_endpoint(self, query_string: str) -> None:
        params = parse_qs(query_string, keep_blank_values=False)
        payload = {
            "genres": ",".join(params.get("genres", [])),
            "subtags": ",".join(params.get("subtags", [])),
            "subtagMatch": str((params.get("subtagMatch") or ["any"])[0]),
            "audience": str((params.get("audience") or ["male"])[0]),
            "words": str((params.get("words") or ["any"])[0]),
            "status": str((params.get("status") or ["all"])[0]),
            "platforms": ",".join(params.get("platforms", [])),
            "mode": str((params.get("mode") or ["mixed"])[0]),
            "exclude": ",".join(params.get("exclude", [])),
            "current": ",".join(params.get("current", [])),
            "allowFallback": False,
        }
        self.discover_payload(payload)

    def discover_payload(self, payload: dict) -> None:
        if not SEARCH_SEMAPHORE.acquire(blocking=False):
            self.send_json({"ok": False, "code": "discover_busy", "message": "正在为其他请求挑书，请稍后再试。"}, HTTPStatus.TOO_MANY_REQUESTS)
            return
        try:
            requested_genres = [item.strip() for item in str(payload.get("genres") or "").split(",") if item.strip()]
            genres = [item for item in requested_genres if item in QIMAO_GENRES][:3]
            requested_subtags = [item.strip() for item in str(payload.get("subtags") or "").split(",") if item.strip()]
            subtags = [item for item in requested_subtags if item in CONTENT_TAG_RULES][:3]
            subtag_match = str(payload.get("subtagMatch") or "any").strip()
            if subtag_match not in {"any", "all"}:
                subtag_match = "any"
            audience = str(payload.get("audience") or "male").strip()
            if audience not in {"male", "female", "all"}:
                audience = "male"
            words_key = str(payload.get("words") or "any").strip()
            if words_key not in WORD_LIMITS and words_key != "any":
                words_key = "any"
            status_key = str(payload.get("status") or "all").strip()
            if status_key not in {"all", "completed", "ongoing"}:
                status_key = "all"
            requested_platforms = [item.strip() for item in str(payload.get("platforms") or "").split(",") if item.strip()]
            platforms = [item for item in DISCOVERY_PLATFORMS if not requested_platforms or item in requested_platforms]
            if not platforms:
                self.send_json({"ok": False, "code": "missing_platform", "message": "请至少选择一个来源平台。"}, HTTPStatus.BAD_REQUEST)
                return
            mode = str(payload.get("mode") or "mixed").strip()
            if mode not in {"popular", "random", "mixed"}:
                mode = "mixed"
            excluded = [item.strip()[:160] for item in str(payload.get("exclude") or "").split(",") if item.strip()][-180:]
            current = [item.strip()[:160] for item in str(payload.get("current") or "").split(",") if item.strip()][-6:]
            # 指定来源始终是硬约束；旧客户端即使传 true 也不能跨平台补足。
            allow_fallback = False
            preferences = sanitize_preference_weights(payload.get("preferences"))
            books, sources, metadata = build_discovery_batch(
                genres, subtags, subtag_match, words_key, status_key, mode, excluded,
                platforms, allow_fallback, preferences, current, audience,
            )
            if not books:
                eligible_count = int(metadata.get("eligibleCount") or 0)
                fresh_count = int(metadata.get("freshEligibleCount") or 0)
                platform_label = "、".join(platforms)
                message = (
                    f"{platform_label}当前条件下暂时只有 {fresh_count} 本新的合格候选，已保留当前结果并在后台扩充书库。"
                    if current else
                    f"{platform_label}当前公开书库在这些条件下只找到 {eligible_count} 本，暂时无法凑齐 6 本。可以放宽篇幅或细分条件。"
                )
                self.send_json({
                    "ok": False,
                    "code": "not_enough_for_fixed_batch",
                    "keepCurrent": True,
                    "eligibleCount": eligible_count,
                    "platforms": platforms,
                    "message": message,
                    **metadata,
                }, HTTPStatus.BAD_GATEWAY)
                return
            self.send_json({
                "ok": True,
                "mode": mode,
                "genres": genres,
                "subtags": subtags,
                "subtagMatch": subtag_match,
                "audience": audience,
                "platforms": platforms,
                "words": words_key,
                "status": status_key,
                "results": books,
                "sources": sources,
                "searchedAt": utc_now(),
                "batchSize": 6,
                "fixedBatch": True,
                **metadata,
                "popularityNote": "热度来自平台公开点击榜、收藏榜或订阅榜名次，不虚构观看人数。",
            })
        finally:
            SEARCH_SEMAPHORE.release()

    def _search_endpoint(self, query_string: str) -> None:
        params = parse_qs(query_string, keep_blank_values=False)
        query = str((params.get("q") or [""])[0]).strip()
        if not query:
            self.send_json({"ok": False, "code": "missing_query", "message": "请输入书名、作者或题材。"}, HTTPStatus.BAD_REQUEST)
            return
        if len(query) > 120:
            self.send_json({"ok": False, "code": "query_too_long", "message": "搜索词最多 120 个字符。"}, HTTPStatus.BAD_REQUEST)
            return
        requested = [item.strip() for item in ",".join(params.get("platforms", [])).split(",") if item.strip()]
        platforms = [item for item in PLATFORM_ORDER if item in requested] or list(PLATFORM_ORDER)
        provider = SEARCH_PROVIDER
        if provider not in {"auto", "direct", "brave"}:
            provider = "auto"

        if provider == "brave" and not BRAVE_SEARCH_API_KEY:
            self.send_json({
                "ok": False,
                "code": "search_not_configured",
                "message": "已选择 Brave 实时汇总，但 VPS 尚未配置 BRAVE_SEARCH_API_KEY。",
                "provider": "brave",
                "platforms": [{"name": item, "url": platform_url(item, query)} for item in platforms],
            }, HTTPStatus.SERVICE_UNAVAILABLE)
            return

        if provider == "brave" or (provider == "auto" and BRAVE_SEARCH_API_KEY):
            results, error = brave_platform_search(query, platforms)
            if error:
                if provider == "brave":
                    status = HTTPStatus.TOO_MANY_REQUESTS if error == "rate-limited" else HTTPStatus.BAD_GATEWAY
                    self.send_json({"ok": False, "code": error, "message": "实时汇总暂时不可用，请稍后重试或打开平台搜索。", "platforms": [{"name": item, "url": platform_url(item, query)} for item in platforms]}, status)
                    return
                results = []
            if results:
                self.send_json({"ok": True, "query": query, "provider": "brave", "mode": "inline", "platforms": platforms, "results": results, "searchedAt": utc_now()})
                return

        results = direct_platform_search(query, platforms)
        self.send_json({
            "ok": True,
            "query": query,
            "provider": "platform",
            "mode": "platform-links",
            "platforms": platforms,
            "results": results,
            "searchedAt": utc_now(),
            "message": "已生成各平台实时搜索结果；部分平台会在打开后由其页面加载书卡。",
        })

    def do_POST(self) -> None:
        self.safe_dispatch(self._do_POST)

    def _do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/hotlists/refresh":
            if not self.require_auth():
                return
            payload = self.read_json()
            board_id = str(payload.get("board", ""))
            if board_id not in hotlists.BOARDS:
                self.send_json({"ok": False, "error": "无效榜单"}, HTTPStatus.BAD_REQUEST)
                return
            if not SEARCH_SEMAPHORE.acquire(blocking=False):
                self.send_json({"ok": False, "error": "采集中，请稍后重试"}, HTTPStatus.TOO_MANY_REQUESTS)
                return
            try:
                result = hotlists.collect(board_id, fetch_html)
                self.send_json(result, HTTPStatus.OK if result["ok"] else HTTPStatus.BAD_GATEWAY)
            finally:
                SEARCH_SEMAPHORE.release()
            return
        if path == "/api/auth/login":
            address = str(self.client_address[0] or "unknown")
            if not auth_attempt_allowed(address):
                self.send_json({"ok": False, "message": "尝试次数过多，请十分钟后再试。"}, HTTPStatus.TOO_MANY_REQUESTS)
                return
            code = str(self.read_json().get("code") or "")[:300]
            if not MISHU_ACCESS_CODE or hmac.compare_digest(code, MISHU_ACCESS_CODE):
                clear_auth_failures(address)
                token = session_token()
                self.send_json(
                    {"ok": True, "required": bool(MISHU_ACCESS_CODE), "authenticated": True},
                    extra_headers={"Set-Cookie": self.auth_cookie(token, MISHU_SESSION_DAYS * 86400)},
                )
            else:
                record_auth_failure(address)
                self.send_json({"ok": False, "message": "访问口令不正确。"}, HTTPStatus.UNAUTHORIZED)
            return
        if path == "/api/auth/logout":
            self.send_json(
                {"ok": True},
                extra_headers={"Set-Cookie": self.auth_cookie("", 0)},
            )
            return
        if path.startswith("/api/") and not self.require_auth():
            return
        if path == "/api/discover":
            self.discover_payload(self.read_json())
            return
        if path in ("/api/events", "/api/sync"):
            self.store_events(self.read_json())
            return
        if path == "/api/sync/token":
            self.sync_create_or_rotate_token(self.read_json())
            return
        if path == "/api/sync/join":
            self.sync_join(self.read_json())
            return
        if path == "/api/sync/push":
            self.sync_push(self.read_json())
            return
        if path == "/api/sync/pull":
            self.sync_pull(self.read_json())
            return
        if path == "/api/sync/disconnect":
            self.sync_disconnect()
            return
        if path == "/api/sync/reset":
            self.sync_reset()
            return
        if path == "/api/source-health/check":
            payload = self.read_json()
            requested = payload.get("platforms")
            platforms = [str(item) for item in requested] if isinstance(requested, list) else None
            started = schedule_source_health_check(platforms)
            self.send_json({"ok": True, "started": started, "message": "已开始低频检查，不会影响当前推荐。"})
            return
        if path == "/api/ai/enrich":
            self.ai_enrich(self.read_json())
            return
        if path == "/api/ai/config":
            self.ai_save_config(self.read_json())
            return
        if path == "/api/ai/test":
            self.ai_test(self.read_json())
            return
        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def ai_save_config(self, payload: dict) -> None:
        device_id = clean_device_id(payload.get("deviceId"))
        if not device_id:
            self.send_json({"ok": False, "message": "设备标识无效，请刷新页面后重试。"}, HTTPStatus.BAD_REQUEST)
            return
        if payload.get("clear") is True:
            delete_device_ai_config(device_id)
            config = ai_config(device_id)
            self.send_json({"ok": True, "enabled": bool(config.get("apiUrl") and config.get("apiKey") and config.get("model"))})
            return
        api_url = str(payload.get("apiUrl") or "").strip()[:500]
        api_key = str(payload.get("apiKey") or "").strip()[:2000]
        model = str(payload.get("model") or "").strip()[:160]
        if not api_url or not model:
            self.send_json({"ok": False, "message": "请填写 API 地址和模型名称。"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            ai_chat_url(api_url)
        except ValueError as error:
            self.send_json({"ok": False, "message": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        current = ai_config(device_id)
        if not api_key and not current.get("apiKey"):
            self.send_json({"ok": False, "message": "首次配置需要填写 API 密钥。"}, HTTPStatus.BAD_REQUEST)
            return
        values = {"apiUrl": api_url, "model": model}
        if api_key:
            values["apiKey"] = api_key
        save_device_ai_config(device_id, values)
        self.send_json({"ok": True, "enabled": True, "apiUrl": api_url, "model": model, "hasKey": True})

    def ai_test(self, payload: dict) -> None:
        config = ai_config(clean_device_id(payload.get("deviceId")))
        try:
            content = call_ai(config, [
                {"role": "system", "content": "只输出JSON。"},
                {"role": "user", "content": "请返回 {\"ok\":true,\"message\":\"连接成功\"}"},
            ], max_tokens=80)
            if not content:
                raise ValueError("AI 返回为空")
            self.send_json({"ok": True, "model": config.get("model", ""), "message": "AI 连接成功"})
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            self.send_json({"ok": False, "message": friendly_ai_error(error)}, HTTPStatus.BAD_GATEWAY)

    def ai_enrich(self, payload: dict) -> None:
        books = payload.get("books", [])
        preferences = payload.get("preferences", {})
        mode = str(payload.get("mode") or "mixed")
        if not isinstance(books, list) or not isinstance(preferences, dict):
            self.send_json({"ok": False, "message": "AI 分析参数不完整。"}, HTTPStatus.BAD_REQUEST)
            return
        if mode not in {"popular", "random", "mixed"}:
            mode = "mixed"
        config = ai_config(clean_device_id(payload.get("deviceId")))
        if not (config.get("apiUrl") and config.get("apiKey") and config.get("model")):
            self.send_json({"ok": False, "enabled": False, "message": "请先在设置中配置 AI API。"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            result, cached = ai_analyze_books(books, preferences, mode, config)
            self.send_json({"ok": True, "enabled": True, "cached": cached, "model": config.get("model", ""), **result})
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            self.send_json({"ok": False, "enabled": True, "message": friendly_ai_error(error)}, HTTPStatus.BAD_GATEWAY)


    def do_HEAD(self) -> None:
        self.safe_dispatch(self._do_HEAD)

    def _do_HEAD(self) -> None:
        path = urlparse(self.path).path
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        if relative == "data/books.json":
            self.send_response(HTTPStatus.GONE)
            self.send_security_headers()
            self.end_headers()
            return
        root = WEB_DIR
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            target = Path("/missing")
        if not target.is_file():
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_security_headers()
            self.end_headers()
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".webmanifest":
            content_type = "application/manifest+json"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_security_headers()
        self.end_headers()

    def store_events(self, payload: dict) -> None:
        events = payload.get("events")
        if not isinstance(events, list):
            self.send_json({"error": "events must be a list"}, HTTPStatus.BAD_REQUEST)
            return
        accepted = 0
        device_id = clean_device_id(payload.get("deviceId"))
        if not device_id:
            self.send_json({"ok": False, "message": "设备标识无效，请刷新页面后重试。"}, HTTPStatus.BAD_REQUEST)
            return
        with DB_LOCK, db_connect() as connection:
            for event in events[:100]:
                if not isinstance(event, dict):
                    continue
                book_id = clean_html_text(str(event.get("bookId") or ""))[:160]
                action = str(event.get("action", "")).strip()[:40]
                happened_at = str(event.get("timestamp", "")).strip()[:80] or utc_now()
                # “shown” 只用于当前设备的换批去重，不写入服务器长期画像。
                if not book_id or action not in SYNC_ACTIONS:
                    continue
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO events(device_id, book_id, action, happened_at) VALUES (?, ?, ?, ?)",
                    (device_id, book_id, action, happened_at),
                )
                accepted += int(cursor.rowcount > 0)
        self.send_json({"ok": True, "accepted": accepted})

    def profile(self, device_id: str = "") -> dict:
        with DB_LOCK, db_connect() as connection:
            if device_id:
                rows = connection.execute(
                    "SELECT action, COUNT(*) AS count FROM events WHERE device_id = ? GROUP BY action", (device_id,),
                ).fetchall()
            else:
                rows = []
        return {"counts": {row["action"]: row["count"] for row in rows}}

    def backup(self, device_id: str = "") -> dict:
        device_id = clean_device_id(device_id)
        if not device_id:
            return {"version": 1, "exportedAt": utc_now(), "events": []}
        with DB_LOCK, db_connect() as connection:
            rows = connection.execute(
                "SELECT book_id, action, happened_at FROM events WHERE device_id = ? ORDER BY id", (device_id,)
            ).fetchall()
        return {"version": 1, "exportedAt": utc_now(), "events": [dict(row) for row in rows]}

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        if relative == "data/books.json":
            self.send_json({"ok": False, "code": "local_catalog_disabled", "message": "觅书不提供内置书库，请使用实时平台搜索。"}, HTTPStatus.GONE)
            return
        root = WEB_DIR
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            body = target.read_bytes()
        except OSError:
            self.send_json({"error": "unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".webmanifest":
            content_type = "application/manifest+json"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache" if target.name == "index.html" else "public, max-age=3600")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(body)


class MishuHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 32


def main() -> None:
    init_db()
    hotlists.init()
    server = MishuHTTPServer((os.environ.get("HOST", "0.0.0.0"), PORT), Handler)
    hotlists.start_daily(fetch_html)
    print(f"觅书服务已启动：http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
