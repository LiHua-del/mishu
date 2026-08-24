"""书旗公开书库、榜单与详情页解析。"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from ..config import SHUQI_RANKS
from .common import absolute_url, clean_book_title, clean_html_text

def parse_shuqi_store(body: str, page_url: str) -> list[dict]:
    """解析书旗官方书库页；书库负责扩大候选，详情页负责确认精确字段。"""
    store_list = re.search(r'<ul\b[^>]*class=["\'][^"\']*store-ul[^"\']*["\'][^>]*>(.*?)</ul>', body, flags=re.I | re.S)
    if not store_list:
        return []
    query = parse_qs(urlparse(page_url).query)
    try:
        page = max(1, int((query.get("page") or ["1"])[0]))
    except (TypeError, ValueError):
        page = 1
    requested_status = (query.get("st") or ["0"])[0]
    status_hint = "连载" if requested_status == "1" else ("完结" if requested_status == "2" else "待核实")
    books: list[dict] = []
    items = re.findall(r'<li\b[^>]*>(.*?)</li>', store_list.group(1), flags=re.I | re.S)
    for local_rank, item in enumerate(items, 1):
        link_match = re.search(r'<a\b[^>]*href=["\']([^"\']*/book/(\d+)\.html)["\'][^>]*>.*?<img\b[^>]*class=["\'][^"\']*cover[^"\']*["\'][^>]*src=["\']([^"\']+)["\'][^>]*>.*?<h3[^>]*>(.*?)</h3>', item, flags=re.I | re.S)
        if not link_match:
            continue
        author_match = re.search(r'<p\b[^>]*class=["\'][^"\']*store-tag[^"\']*["\'][^>]*>.*?<a\b[^>]*>\s*作者[：:]?\s*(.*?)</a>', item, flags=re.I | re.S)
        category_match = re.search(r'<p\b[^>]*class=["\'][^"\']*store-tag[^"\']*["\'][^>]*>.*?<span[^>]*>(.*?)</span>', item, flags=re.I | re.S)
        description_match = re.search(r'<p\b[^>]*class=["\'][^"\']*store-des[^"\']*["\'][^>]*>(.*?)</p>', item, flags=re.I | re.S)
        rank = (page - 1) * 36 + local_rank
        category = clean_html_text(category_match.group(1)) if category_match else ""
        books.append({
            "id": "shuqi-" + link_match.group(2),
            "platform": "书旗",
            "title": clean_book_title(link_match.group(4))[:160],
            "author": clean_html_text(author_match.group(1))[:80] if author_match else "未知作者",
            "description": clean_html_text(description_match.group(1))[:1200] if description_match else "",
            "url": absolute_url(link_match.group(1), page_url),
            "cover": absolute_url(link_match.group(3), page_url).replace("http://", "https://", 1),
            "genres": [category] if category else [],
            "words": 0,
            "status": status_hint,
            "rank": rank,
            "popularityScore": max(48, 82 - min(rank, 68) * 0.35),
            "popularityText": f"书旗书库 #{rank}",
            "sourceType": "store",
        })
    return books


def parse_shuqi_rank(body: str, page_url: str, rank_kind: str = "allOrder") -> list[dict]:
    rank_list = re.search(r'<ul\b[^>]*class=["\']ranklist-ul["\'][^>]*>(.*?)</ul>', body, flags=re.I | re.S)
    if not rank_list:
        return []
    page_values = parse_qs(urlparse(page_url).query).get("page", ["1"])
    try:
        page = max(1, int(page_values[0]))
    except (TypeError, ValueError):
        page = 1
    rank_label = SHUQI_RANKS.get(rank_kind, "实时榜")
    books: list[dict] = []
    for local_rank, item in enumerate(re.findall(r'<li\b[^>]*class=["\']clearfix["\'][^>]*>(.*?)</li>', rank_list.group(1), flags=re.I | re.S), 1):
        rank = (page - 1) * 10 + local_rank
        title_match = re.search(r'<a\b[^>]*href=["\']([^"\']*/book/[^"\']+)["\'][^>]*>\s*<h3>(.*?)</h3>', item, flags=re.I | re.S)
        cover_match = re.search(r'<img\b[^>]*src=["\']([^"\']+)["\'][^>]*alt=', item, flags=re.I | re.S)
        if not title_match or not cover_match:
            continue
        author_match = re.search(r'class=["\']bkuser-icon["\'][^>]*>\s*<a\b[^>]*>(.*?)</a>', item, flags=re.I | re.S)
        category_match = re.search(r'class=["\']bkcate-icon["\'][^>]*>(.*?)</span>', item, flags=re.I | re.S)
        desc_match = re.search(r'<p\b[^>]*class=["\']ranklist-des["\'][^>]*>(.*?)</p>', item, flags=re.I | re.S)
        target = absolute_url(title_match.group(1), page_url)
        bid_match = re.search(r'/book/(\d+)', target)
        if not bid_match:
            continue
        category = clean_html_text(category_match.group(1)) if category_match else ""
        books.append({
            "id": "shuqi-" + bid_match.group(1),
            "platform": "书旗",
            "title": clean_book_title(title_match.group(2))[:160],
            "author": clean_html_text(author_match.group(1))[:80] if author_match else "未知作者",
            "description": clean_html_text(desc_match.group(1))[:500] if desc_match else "",
            "url": target,
            "cover": absolute_url(cover_match.group(1), page_url).replace("http://", "https://", 1),
            "genres": [category] if category else [],
            "words": 0,
            "status": "待核实",
            "rank": rank,
            "popularityScore": max(42, 100 - local_rank * 2 - (page - 1) * 2),
            "popularityText": f"书旗{rank_label} #{rank}",
            "sourceType": rank_kind,
        })
    return books


def parse_shuqi_detail(body: str, page_url: str) -> list[dict]:
    book_id_match = re.search(r"/book/(\d+)", page_url)
    if not book_id_match:
        return []
    last_chapter_match = re.search(r'<div\b[^>]*class=["\'][^"\']*lastchapter[^"\']*["\'][^>]*>(.*?)</div>', body, flags=re.I | re.S)
    text = clean_html_text(last_chapter_match.group(1)) if last_chapter_match else clean_html_text(body[:30000])
    words_match = re.search(r'([0-9.]+)\s*万字', text)
    status_match = re.search(r'(完结|连载)', text)
    title_match = re.search(r'<span\b[^>]*class=["\'][^"\']*bname[^"\']*["\'][^>]*>(.*?)</span>', body, flags=re.I | re.S)
    author_match = re.search(r'<div\b[^>]*class=["\'][^"\']*bauthor[^"\']*["\'][^>]*>.*?<a\b[^>]*>(.*?)</a>', body, flags=re.I | re.S)
    cover_match = re.search(r'<div\b[^>]*class=["\'][^"\']*view[^"\']*["\'][^>]*>\s*<img\b[^>]*src=["\']([^"\']+)["\']', body, flags=re.I | re.S)
    tags_block = re.search(r'<div\b[^>]*class=["\'][^"\']*tags[^"\']*["\'][^>]*>(.*?)</div>', body, flags=re.I | re.S)
    official_tags = [clean_html_text(value) for value in re.findall(r'<a\b[^>]*>(.*?)</a>', tags_block.group(1), flags=re.I | re.S)] if tags_block else []
    chapter_items = [clean_html_text(value) for value in re.findall(r'<li\b[^>]*>(.*?)</li>', last_chapter_match.group(1), flags=re.I | re.S)] if last_chapter_match else []
    categories = [item for item in chapter_items if item and "万字" not in item and not re.search(r'(完结|连载|更新)', item)]
    description_match = re.search(r'\bdata-text=["\'](.*?)["\']\s*>\s*展开', body, flags=re.I | re.S)
    if not description_match:
        description_match = re.search(r'<span\b[^>]*class=["\'][^"\']*js-descContent[^"\']*["\'][^>]*>(.*?)</span>', body, flags=re.I | re.S)
    hot_match = re.search(r'热度[：:]\s*([0-9.]+)\s*([Ww万]?)', body)
    popularity = 0.0
    if hot_match:
        popularity = float(hot_match.group(1)) * (10000 if hot_match.group(2) else 1)
    if not words_match and not status_match and not title_match:
        return []
    return [{
        "id": "shuqi-" + book_id_match.group(1),
        "title": clean_book_title(title_match.group(1))[:160] if title_match else "",
        "author": clean_html_text(author_match.group(1))[:80] if author_match else "",
        "description": clean_html_text(description_match.group(1))[:1200] if description_match else "",
        "cover": absolute_url(cover_match.group(1), page_url).replace("http://", "https://", 1) if cover_match else "",
        "words": float(words_match.group(1)) if words_match else 0,
        "status": status_match.group(1) if status_match else "待核实",
        "genres": list(dict.fromkeys(categories + official_tags))[:10],
        "popularityScore": min(100, 55 + (popularity ** 0.25) * 3) if popularity else 0,
    }]
