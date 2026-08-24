"""起点公开榜单、分类书库与详情页解析。"""

from __future__ import annotations

import re

from .common import absolute_url, clean_book_title, clean_html_text

def parse_qidian_rank(body: str, page_url: str) -> list[dict]:
    books: list[dict] = []
    items = re.findall(r'<div\b[^>]*class=["\']y-list__item["\'][^>]*>(.*?)(?=<div\b[^>]*class=["\']y-list__item["\']|$)', body, flags=re.I | re.S)
    for index, item in enumerate(items, 1):
        link_match = re.search(r'<a\b[^>]*href=["\']([^"\']*/book/(\d+)/?)["\']', item, flags=re.I | re.S)
        title_match = re.search(r'<h2\b[^>]*>(.*?)</h2>', item, flags=re.I | re.S)
        cover_match = re.search(r'<img\b[^>]*data-src=["\']([^"\']+)["\']', item, flags=re.I | re.S)
        sub_match = re.search(r'<p\b[^>]*class=["\'][^"\']*_subTitle_[^"\']*["\'][^>]*>(.*?)</p>', item, flags=re.I | re.S)
        if not link_match or not title_match or not cover_match or not sub_match:
            continue
        sub_parts = [clean_html_text(part) for part in re.split(r'<em\b[^>]*>.*?</em>', sub_match.group(1), flags=re.I | re.S)]
        sub_parts = [part for part in sub_parts if part]
        words_match = re.search(r'([0-9.]+)\s*万字', clean_html_text(sub_match.group(1)))
        votes_match = re.search(r'<div\b[^>]*class=["\'][^"\']*_bookTitleR_[^"\']*["\'][^>]*>(.*?)</div>', item, flags=re.I | re.S)
        desc_match = re.search(r'<p\b[^>]*class=["\'][^"\']*_bookDesc_[^"\']*["\'][^>]*>(.*?)</p>', item, flags=re.I | re.S)
        rank_match = re.search(r'<div\b[^>]*class=["\'][^"\']*_ranking_[^"\']*["\'][^>]*>\s*(\d+)', item, flags=re.I | re.S)
        rank = int(rank_match.group(1)) if rank_match else index
        category = sub_parts[1] if len(sub_parts) > 1 else ""
        vote_text = clean_html_text(votes_match.group(1)) if votes_match else ""
        books.append({
            "id": "qidian-" + link_match.group(2),
            "platform": "起点",
            "title": clean_book_title(title_match.group(1))[:160],
            "author": sub_parts[0][:80] if sub_parts else "未知作者",
            "description": clean_html_text(desc_match.group(1))[:500] if desc_match else "",
            "url": absolute_url(link_match.group(1), page_url),
            "cover": absolute_url(cover_match.group(1), page_url).replace("http://", "https://", 1),
            "genres": [category] if category else [],
            "words": float(words_match.group(1)) if words_match else 0,
            "status": "待核实",
            "rank": rank,
            "popularityScore": max(55, 104 - rank * 2),
            "popularityText": vote_text or f"起点月票榜 #{rank}",
            "sourceType": "monthly-votes",
        })
    return books


def parse_qidian_listing(body: str, page_url: str, source_label: str = "分类书库") -> list[dict]:
    """解析起点移动端分类/搜索列表；字段随后仍由官方详情页二次确认。"""
    items = re.findall(r'<div\b[^>]*class=["\']y-list__item["\'][^>]*>(.*?)(?=<div\b[^>]*class=["\']y-list__item["\']|$)', body, flags=re.I | re.S)
    books: list[dict] = []
    for rank, item in enumerate(items, 1):
        link_match = re.search(r'<a\b[^>]*href=["\']([^"\']*/book/(\d+)/?)["\']', item, flags=re.I | re.S)
        title_match = re.search(r'<h2\b[^>]*>(.*?)</h2>', item, flags=re.I | re.S)
        cover_match = re.search(r'<img\b[^>]*data-src=["\']([^"\']+)["\']', item, flags=re.I | re.S)
        if not link_match or not title_match or not cover_match:
            continue
        description_match = re.search(r'<p\b[^>]*class=["\'][^"\']*_bookSubTitle_[^"\']*["\'][^>]*>(.*?)</p>', item, flags=re.I | re.S)
        author_match = re.search(r'<p\b[^>]*class=["\'][^"\']*_bookTip_[^"\']*["\'][^>]*>(.*?)</p>', item, flags=re.I | re.S)
        tags_match = re.search(r'<div\b[^>]*class=["\'][^"\']*_tags_[^"\']*["\'][^>]*>(.*?)</div>', item, flags=re.I | re.S)
        tags = [clean_html_text(value) for value in re.findall(r'<p\b[^>]*>(.*?)</p>', tags_match.group(1), flags=re.I | re.S)] if tags_match else []
        status = next((value for value in tags if "连载" in value or "完结" in value), "待核实")
        words_match = next((re.search(r'([0-9.]+)\s*万字', value) for value in tags if "万字" in value), None)
        genres = [value for value in tags if value and "万字" not in value and "连载" not in value and "完结" not in value]
        books.append({
            "id": "qidian-" + link_match.group(2),
            "platform": "起点",
            "title": clean_book_title(title_match.group(1))[:160],
            "author": clean_html_text(author_match.group(1))[:80] if author_match else "未知作者",
            "description": clean_html_text(description_match.group(1))[:1200] if description_match else "",
            "url": absolute_url(link_match.group(1), page_url),
            "cover": absolute_url(cover_match.group(1), page_url).replace("http://", "https://", 1),
            "genres": genres[:4],
            "words": float(words_match.group(1)) if words_match else 0,
            "status": status,
            "rank": rank,
            "popularityScore": max(50, 92 - rank * 1.2),
            "popularityText": f"起点{source_label} #{rank}",
            "sourceType": "category" if source_label == "分类书库" else "content-search",
        })
    return books


def parse_qidian_category_json(payload: dict, category_label: str, page_num: int, order_by: str) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else {}
    records = data.get("records", []) if isinstance(data, dict) else []
    books: list[dict] = []
    for local_rank, item in enumerate(records, 1):
        if not isinstance(item, dict):
            continue
        bid = str(item.get("bid") or "").strip()
        title = clean_book_title(str(item.get("bName") or ""))
        if not bid or not title:
            continue
        words_match = re.search(r"([0-9.]+)\s*万字", str(item.get("cnt") or ""))
        category = clean_html_text(str(item.get("cat") or category_label))
        rank = (page_num - 1) * 20 + local_rank
        books.append({
            "id": "qidian-" + bid,
            "platform": "起点",
            "title": title[:160],
            "author": clean_html_text(str(item.get("bAuth") or "未知作者"))[:80],
            "description": clean_html_text(str(item.get("desc") or ""))[:1200],
            "url": f"https://m.qidian.com/book/{bid}/",
            "cover": f"https://bookcover.yuewen.com/qdbimg/349573/{bid}/180",
            "genres": [category] if category else [],
            "words": float(words_match.group(1)) if words_match else 0,
            "status": clean_html_text(str(item.get("state") or "待核实")),
            "rank": rank,
            "popularityScore": max(48, (96 if order_by == "2" else 88) - min(rank, 140) * 0.25),
            "popularityText": f"起点分类书库 #{rank}",
            "sourceType": "category-api",
        })
    return books


def parse_qidian_detail(body: str, page_url: str) -> list[dict]:
    book_id_match = re.search(r"/book/(\d+)", page_url)
    if not book_id_match:
        return []
    status_match = re.search(r'<meta\b[^>]*property=["\']og:novel:status["\'][^>]*content=["\']([^"\']+)', body, flags=re.I | re.S)
    words_match = re.search(r'<span\b[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>\s*([0-9.]+)\s*</span>\s*<span\b[^>]*class=["\'][^"\']*unit[^"\']*["\'][^>]*>\s*万字', body, flags=re.I | re.S)
    category_matches = re.findall(r'<a\b[^>]*class=["\'][^"\']*category[^"\']*["\'][^>]*>(.*?)</a>', body, flags=re.I | re.S)
    genres = [clean_html_text(value) for value in category_matches if clean_html_text(value)]
    description_match = re.search(r'<meta\b[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']*)', body, flags=re.I | re.S)
    if not status_match and not words_match and not genres:
        return []
    return [{
        "id": "qidian-" + book_id_match.group(1),
        "description": clean_html_text(description_match.group(1))[:1200] if description_match else "",
        "words": float(words_match.group(1)) if words_match else 0,
        "status": clean_html_text(status_match.group(1)) if status_match else "待核实",
        "genres": list(dict.fromkeys(genres))[:4],
    }]
