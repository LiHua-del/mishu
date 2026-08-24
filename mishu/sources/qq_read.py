"""QQ 阅读榜单与分类书库解析。"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..config import QQ_RANKS
from .common import absolute_url, clean_book_title, clean_html_text

def qq_cover_url(bid: str) -> str:
    folder = str(int(bid[-3:])) if bid[-3:].isdigit() else bid[-3:].lstrip("0") or "0"
    return f"https://wfqqreader-1252317822.image.myqcloud.com/cover/{folder}/{bid}/t6_{bid}.jpg"


def parse_qq_rank(body: str, page_url: str, rank_kind: str = "sell") -> list[dict]:
    books: list[dict] = []
    page_match = re.search(r"/cycle-\d+-(\d+)(?:/|$)", page_url)
    page = int(page_match.group(1)) if page_match else 1
    rank_label = QQ_RANKS.get(rank_kind, "热门榜")
    items = re.findall(r'<div\b[^>]*class=["\']book-large rank-book["\'][^>]*>(.*?)(?=<div\b[^>]*class=["\']book-large rank-book["\']|$)', body, flags=re.I | re.S)
    for local_rank, item in enumerate(items, 1):
        rank = (page - 1) * 20 + local_rank
        link_match = re.search(r'<a\b[^>]*title=["\']([^"\']+)["\'][^>]*href=["\']([^"\']*/book-detail/(\d+))["\']', item, flags=re.I | re.S)
        if not link_match:
            continue
        bid = link_match.group(3)
        intro_match = re.search(r'<p\b[^>]*class=["\']intro["\'][^>]*>(.*?)</p>', item, flags=re.I | re.S)
        other_match = re.search(r'<p\b[^>]*class=["\']other["\'][^>]*>(.*?)</p>', item, flags=re.I | re.S)
        other = other_match.group(1) if other_match else ""
        anchors = [clean_html_text(value) for value in re.findall(r'<a\b[^>]*>(.*?)</a>', other, flags=re.I | re.S)]
        anchors = [value.lstrip("·").strip() for value in anchors if value.strip()]
        status_match = re.search(r'·\s*(连载|完结)', clean_html_text(other))
        words_match = re.search(r'·\s*([0-9.]+)\s*万字', clean_html_text(other))
        category = anchors[1] if len(anchors) > 1 else ""
        books.append({
            "id": "qq-" + bid,
            "platform": "QQ阅读",
            "title": clean_book_title(link_match.group(1))[:160],
            "author": anchors[0][:80] if anchors else "未知作者",
            "description": clean_html_text(intro_match.group(1))[:500] if intro_match else "",
            "url": absolute_url(link_match.group(2), page_url),
            "cover": qq_cover_url(bid),
            "genres": [category] if category else [],
            "words": float(words_match.group(1)) if words_match else 0,
            "status": status_match.group(1) if status_match else "待核实",
            "rank": rank,
            "popularityScore": max(45, 103 - local_rank * 2 - (page - 1) * 2),
            "popularityText": f"QQ阅读{rank_label} #{rank}",
            "sourceType": rank_kind + "-rank",
        })
    return books


def parse_qq_category(body: str, page_url: str) -> list[dict]:
    """QQ 阅读书库与榜单使用同一种书卡；书库页负责扩大按条件筛过的候选。"""
    books = parse_qq_rank(body, page_url, "sell")
    path = urlparse(page_url).path.rstrip("/")
    page_match = re.search(r"/book-cate/(?:[^/]*-){7}(\d+)$", path)
    page = int(page_match.group(1)) if page_match else 1
    sort_match = re.search(r"/book-cate/(?:[^/]*-){6}(\d+)-\d+$", path)
    sort_value = sort_match.group(1) if sort_match else "0"
    sort_label = {"0": "人气", "1": "收藏", "2": "畅销", "3": "更新", "4": "字数"}.get(sort_value, "人气")
    for local_rank, book in enumerate(books, 1):
        rank = (page - 1) * 20 + local_rank
        book["rank"] = rank
        book["popularityScore"] = max(48, 94 - min(rank, 100) * 0.35)
        book["popularityText"] = f"QQ阅读书库{sort_label} #{rank}"
        book["sourceType"] = "category-" + sort_value
    return books
