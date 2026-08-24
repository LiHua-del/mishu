"""番茄公开推荐、书库、榜单与详情页解析。"""

from __future__ import annotations

import json
import re

from ..config import FANQIE_RANK_FONT_HASH, FANQIE_RANK_FONT_MAP
from .common import clean_book_title, clean_html_text

def parse_fanqie_recommend(payload: dict, list_type: str) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else {}
    items = data.get("list", []) if isinstance(data, dict) else []
    books: list[dict] = []
    for rank, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        bid = str(item.get("bookId") or "").strip()
        title = clean_book_title(str(item.get("bookName") or ""))
        cover = str(item.get("thumbUri") or "").replace("\\u002F", "/").replace("http://", "https://", 1)
        if not bid or not title or not cover:
            continue
        category = clean_html_text(str(item.get("category") or ""))
        books.append({
            "id": "fanqie-" + bid,
            "platform": "番茄",
            "title": title[:160],
            "author": clean_html_text(str(item.get("author") or "未知作者"))[:80],
            "description": clean_html_text(str(item.get("abstract") or ""))[:500],
            "url": f"https://fanqienovel.com/page/{bid}",
            "cover": cover,
            "genres": [category] if category else [],
            "words": 0,
            "status": "待核实",
            "rank": rank,
            "popularityScore": max(54, 102 - rank * 2),
            "popularityText": f"番茄官方推荐 #{rank}",
            "sourceType": "editor" if list_type == "0" else "popular",
        })
    return books


def parse_fanqie_library(payload: dict, category_label: str, page_index: int, sort_value: str) -> list[dict]:
    """番茄书库接口的文字使用站内字体；这里只取 ID/封面，详情页再确认可读文字和字段。"""
    data = payload.get("data") if isinstance(payload, dict) else {}
    items = data.get("book_list", []) if isinstance(data, dict) else []
    books: list[dict] = []
    for local_rank, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        bid = str(item.get("book_id") or item.get("bookId") or "").strip()
        cover = str(item.get("thumb_url") or item.get("thumbUrl") or "").replace("\\u002F", "/").replace("http://", "https://", 1)
        if not bid or not cover:
            continue
        rank = page_index * 18 + local_rank
        creation_status = item.get("creation_status")
        status = "完结" if str(creation_status) == "0" else "连载"
        books.append({
            "id": "fanqie-" + bid,
            "platform": "番茄",
            "title": f"番茄小说 {bid}",
            "author": "待详情确认",
            "description": "",
            "url": f"https://fanqienovel.com/page/{bid}",
            "cover": cover,
            "genres": [category_label] if category_label else [],
            "words": 0,
            "status": status,
            "rank": rank,
            "popularityScore": max(48, (92 if sort_value == "0" else 84) - min(rank, 100) * 0.3),
            "popularityText": f"番茄书库 #{rank}",
            "sourceType": "library-hot" if sort_value == "0" else "library-new",
        })
    return books


def decode_fanqie_rank_text(value: object, body: str) -> str:
    text = str(value or "")
    if not FANQIE_RANK_FONT_HASH or FANQIE_RANK_FONT_HASH not in body:
        return text
    return "".join(FANQIE_RANK_FONT_MAP.get(character, character) for character in text)


def parse_fanqie_rank(body: str, page_url: str, category_label: str) -> list[dict]:
    marker = "window.__INITIAL_STATE__="
    marker_pos = body.find(marker)
    if marker_pos < 0:
        return []
    try:
        payload, _ = json.JSONDecoder().raw_decode(body[marker_pos + len(marker):])
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    rank_data = payload.get("rank") if isinstance(payload, dict) else {}
    items = rank_data.get("book_list", []) if isinstance(rank_data, dict) else []
    rank_type_match = re.search(r"/rank/[01]_([12])_", page_url)
    rank_type = rank_type_match.group(1) if rank_type_match else "2"
    rank_label = "新书榜" if rank_type == "1" else "阅读榜"
    books: list[dict] = []
    for fallback_rank, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        bid = str(item.get("bookId") or "").strip()
        cover = str(item.get("thumbUri") or "").replace("\\u002F", "/").replace("http://", "https://", 1)
        title = clean_book_title(decode_fanqie_rank_text(item.get("bookName"), body))
        if not bid or not cover:
            continue
        rank = int(item.get("currentPos") or fallback_rank)
        raw_words = str(item.get("wordNumber") or "0")
        try:
            words = round(int(raw_words) / 10000, 2)
        except (TypeError, ValueError):
            words = 0
        creation_status = item.get("creationStatus")
        status = "完结" if str(creation_status) == "0" else "连载"
        books.append({
            "id": "fanqie-" + bid,
            "platform": "番茄",
            "title": title[:160] or f"番茄小说 {bid}",
            "author": clean_html_text(decode_fanqie_rank_text(item.get("author") or "未知作者", body))[:80],
            "description": clean_html_text(decode_fanqie_rank_text(item.get("abstract"), body))[:500],
            "url": f"https://fanqienovel.com/page/{bid}",
            "cover": cover,
            "genres": [category_label] if category_label else [],
            "words": words,
            "status": status,
            "rank": rank,
            "popularityScore": max(52, (102 if rank_type == "2" else 96) - rank * 2),
            "popularityText": f"番茄{category_label}{rank_label} #{rank}" if category_label else f"番茄{rank_label} #{rank}",
            "sourceType": "category-new" if rank_type == "1" else "category-read",
        })
    return books


def parse_fanqie_rank_categories(body: str) -> list[tuple[str, str, str]]:
    """从番茄榜单导航动态发现男、女频道分类，避免固定小表逐渐过期。"""
    categories: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    pattern = r'<a\b[^>]*href=["\']/rank/([01])_[12]_(\d+)["\'][^>]*>(.*?)</a>'
    for gender, category_id, raw_label in re.findall(pattern, body, flags=re.I | re.S):
        label = clean_html_text(raw_label)[:40]
        key = (gender, category_id)
        if not label or key in seen:
            continue
        seen.add(key)
        categories.append((gender, category_id, label))
    return categories

def parse_fanqie_detail(body: str, page_url: str) -> list[dict]:
    book_id_match = re.search(r"/page/(\d+)", page_url)
    if not book_id_match:
        return []
    status_match = re.search(r'<span\b[^>]*class=["\']info-label-yellow["\'][^>]*>(.*?)</span>', body, flags=re.I | re.S)
    words_match = re.search(r'class=["\']info-count-word["\'][^>]*>.*?class=["\']detail["\'][^>]*>\s*([0-9.]+)', body, flags=re.I | re.S)
    category_matches = re.findall(r'<span\b[^>]*class=["\']info-label-grey["\'][^>]*>(.*?)</span>', body, flags=re.I | re.S)
    title_match = re.search(r'<div\b[^>]*class=["\']info-name["\'][^>]*>\s*<h1[^>]*>(.*?)</h1>', body, flags=re.I | re.S)
    author_match = re.search(r'<span\b[^>]*class=["\']author-name-text["\'][^>]*>(.*?)</span>', body, flags=re.I | re.S)
    description_match = re.search(r'<div\b[^>]*class=["\']page-abstract-content["\'][^>]*>(.*?)</div>', body, flags=re.I | re.S)
    if not status_match and not words_match:
        return []
    return [{
        "id": "fanqie-" + book_id_match.group(1),
        "title": clean_book_title(decode_fanqie_rank_text(title_match.group(1), body))[:160] if title_match else "",
        "author": clean_html_text(decode_fanqie_rank_text(author_match.group(1), body))[:80] if author_match else "",
        "description": clean_html_text(decode_fanqie_rank_text(description_match.group(1), body))[:500] if description_match else "",
        "words": float(words_match.group(1)) if words_match else 0,
        "status": clean_html_text(status_match.group(1)).replace("中", "") if status_match else "待核实",
        "genres": [clean_html_text(value) for value in category_matches if clean_html_text(value)][:4],
    }]
