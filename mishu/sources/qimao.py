"""七猫公开书库解析。"""

from __future__ import annotations

import re

from .common import absolute_url, clean_book_title, clean_html_text

def parse_qimao_discovery(body: str, page_url: str, order: str) -> list[dict]:
    books: list[dict] = []
    items = re.findall(r'<li\b[^>]*class=["\'][^"\']*qm-cover-text-item[^"\']*["\'][^>]*>(.*?)</li>', body, flags=re.I | re.S)
    order_label = {"click": "点击榜", "favorite_uv": "收藏榜", "update_time": "活跃新书"}.get(order, "实时书库")
    for rank, item in enumerate(items, 1):
        cover_match = re.search(r'<img\b[^>]*src=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*book-cover-src', item, flags=re.I | re.S)
        title_match = re.search(r'<span\b[^>]*class=["\']s-tit["\'][^>]*>\s*<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', item, flags=re.I | re.S)
        if not cover_match or not title_match:
            continue
        author_match = re.search(r'<a\b[^>]*class=["\']s-author["\'][^>]*>(.*?)</a>', item, flags=re.I | re.S)
        category_match = re.search(r'<a\b[^>]*class=["\']s-category["\'][^>]*>(.*?)</a>', item, flags=re.I | re.S)
        status_match = re.search(r'<em\b[^>]*class=["\']s-status["\'][^>]*>(.*?)</em>', item, flags=re.I | re.S)
        words_match = re.search(r'<em\b[^>]*class=["\']s-words-num["\'][^>]*>\s*([0-9.]+)\s*万字', item, flags=re.I | re.S)
        desc_match = re.search(r'<span\b[^>]*class=["\']s-desc["\'][^>]*>(.*?)</span>', item, flags=re.I | re.S)
        target = absolute_url(title_match.group(1), page_url)
        book_id_match = re.search(r'/shuku/(\d+)/?', target)
        if not book_id_match:
            continue
        category = clean_html_text(category_match.group(1)) if category_match else ""
        cover = absolute_url(cover_match.group(1), page_url).replace("http://", "https://", 1)
        if "default-book-cover" in cover or "default_cover" in cover:
            continue
        books.append({
            "id": "qimao-" + book_id_match.group(1),
            "platform": "七猫",
            "title": clean_book_title(title_match.group(2))[:160],
            "author": clean_html_text(author_match.group(1))[:80] if author_match else "未知作者",
            "description": clean_html_text(desc_match.group(1))[:500] if desc_match else "",
            "url": target,
            "cover": cover,
            "genres": [category] if category else [],
            "words": float(words_match.group(1)) if words_match else 0,
            "status": clean_html_text(status_match.group(1)).replace("中", "") if status_match else "待核实",
            "rank": rank,
            "popularityScore": max(50, 101 - rank * 2),
            "popularityText": f"{order_label} #{rank}",
            "sourceType": order,
        })
    return books
