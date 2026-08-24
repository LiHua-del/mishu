"""平台结果清洗与通用搜索页解析。"""

from __future__ import annotations

import html as html_lib
import json
import re
import unicodedata
from urllib.parse import quote, urljoin

from ..config import PLATFORM_SEARCH

def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def platform_url(platform: str, query: str) -> str:
    template = PLATFORM_SEARCH[platform]["url"]
    return template.format(query=quote(query, safe=""))


def clean_html_text(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html_lib.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def clean_book_title(value: str) -> str:
    value = clean_html_text(value)
    # Search pages often wrap every highlighted Chinese character in <i> tags,
    # which otherwise leaves artificial spaces in the copied title.
    return re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", value)


def as_wan(value: object) -> float:
    """把接口中的字数或“万字”文本规范为万字，未知值返回 0。"""
    text = clean_html_text(str(value or ""))
    match = re.search(r"([0-9.]+)", text)
    if not match:
        return 0.0
    try:
        amount = float(match.group(1))
    except ValueError:
        return 0.0
    return round(amount if "万" in text or amount < 10_000 else amount / 10_000, 2)


def absolute_url(url: str, base_url: str) -> str:
    value = html_lib.unescape(url.strip())
    if value.startswith("//"):
        return "https:" + value
    return urljoin(base_url, value)


def _result(platform: str, title: str, url: str, author: str = "未知作者", description: str = "", *, search_page: bool = False, cover: str = "") -> dict:
    title = clean_book_title(title)[:160]
    author = clean_html_text(author)[:80] or "未知作者"
    description = clean_html_text(description)[:500]
    return {
        "platform": platform,
        "title": title,
        "bookTitle": title,
        "author": author,
        "description": description or "平台实时搜索结果，可打开查看详情。",
        "url": url,
        "cover": cover,
        "isSearchPage": search_page,
    }


def _nearby_author(fragment: str) -> str:
    match = re.search(r"(?:作者|作家|著)\s*[：:]?\s*([^<\n]{1,60})", fragment, flags=re.I)
    return clean_html_text(match.group(1)) if match else "未知作者"


def parse_platform_html(platform: str, body: str, page_url: str) -> list[dict]:
    """Extract only public book cards when a platform renders them server-side.

    Several platforms render search results with JavaScript or return anti-bot
    pages. In those cases the caller keeps the platform's live search link so
    the user can still see the current results in the platform itself.
    """
    results: list[dict] = []
    seen: set[str] = set()

    def add(title: str, url: str, context: str = "") -> None:
        cleaned_title = clean_html_text(title)
        if len(cleaned_title) < 2 or cleaned_title in {"搜索", "首页", "登录", "注册"}:
            return
        target = absolute_url(url, page_url)
        if not target.startswith(("http://", "https://")) or target in seen:
            return
        seen.add(target)
        author = _nearby_author(context)
        description = ""
        intro = re.search(r"(?:简介|内容简介|摘要)\s*[：:]?\s*([^<]{20,260})", context, flags=re.I)
        if intro:
            description = intro.group(1)
        cover = ""
        image = re.search(r"<img\b[^>]*(?:src|data-src)\s*=\s*[\"']([^\"']+)", context, flags=re.I | re.S)
        if image:
            cover = absolute_url(image.group(1), page_url)
        results.append(_result(platform, cleaned_title, target, author, description, cover=cover))

    # 书旗 serves a stable HTML list. The highlighted title may contain <i> tags.
    if platform == "书旗":
        patterns = [
            r'<a\b[^>]*class=["\'][^"\']*\bellipsis\b[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            r'<a\b[^>]*class=["\'][^"\']*\bbname\b[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, body, flags=re.I | re.S):
                card_start = body.rfind("<li", 0, match.start())
                context = body[max(0, card_start):match.end() + 900]
                add(match.group(2), match.group(1), context)
                if len(results) >= 8:
                    return results

    # Other sites occasionally include cards in the initial HTML. Keep the
    # selectors deliberately narrow so menus and navigation are not returned.
    generic_patterns = [
        r'<a\b[^>]*href=["\']((?:/page/\d+)|(?:/book/[^"\']+)|(?:https?://book\.qidian\.com/[^"\']+))["\'][^>]*>(.*?)</a>',
        r'<a\b[^>]*class=["\'][^"\']*\bbook(?:-title|Title|name)\b[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    ]
    for pattern in generic_patterns:
        for match in re.finditer(pattern, body, flags=re.I | re.S):
            context = body[max(0, body.rfind("<li", 0, match.start())):match.end() + 900]
            add(match.group(2), match.group(1), context)
            if len(results) >= 8:
                return results
    return results
