"""候选去重、频道判断、条件过滤与内容标签。"""

from __future__ import annotations

import re
import unicodedata

from ..config import CONTENT_TAG_RULES, GENRE_ALIASES, PRIMARY_DISCOVERY_PLATFORMS, SUBTAG_EQUIVALENTS, TAG_NEGATIONS, WORD_LIMITS
from ..sources.common import clean_book_title, clean_html_text
from ..sources.qq_read import qq_cover_url

def canonical_book_key(book: dict) -> str:
    """跨平台识别同一本书；作者未知时不只按书名合并，避免误伤同名作品。"""
    title = unicodedata.normalize("NFKC", clean_book_title(str(book.get("title") or ""))).lower()
    title = re.sub(r"[\W_]+", "", title, flags=re.UNICODE)
    author = unicodedata.normalize("NFKC", clean_html_text(str(book.get("author") or ""))).lower()
    author = re.sub(r"^(作者|作家)[：:]?", "", author)
    author = re.sub(r"[\W_]+", "", author, flags=re.UNICODE)
    if not title or not author or author in {"未知作者", "佚名", "待详情确认"}:
        return "id:" + str(book.get("id") or "")
    return f"work:{title}:{author}"


def candidate_identity_quality(book: dict) -> tuple[int, int, float]:
    """同书多来源时保留资料更完整的一条，主来源只作为最后的轻量优先项。"""
    completeness = sum(bool(book.get(field)) for field in ("cover", "description", "words", "status", "url"))
    primary = 1 if str(book.get("platform") or "") in PRIMARY_DISCOVERY_PLATFORMS else 0
    return completeness, primary, float(book.get("popularityScore") or 0)


def unique_book_candidates(books: list[dict], excluded: set[str] | None = None) -> list[dict]:
    ignored = excluded or set()
    positions: dict[str, int] = {}
    seen_ids: set[str] = set()
    unique: list[dict] = []
    for book in books:
        book_id = str(book.get("id") or "")
        if not book_id or book_id in ignored or book_id in seen_ids:
            continue
        seen_ids.add(book_id)
        key = canonical_book_key(book)
        if key in positions:
            index = positions[key]
            if candidate_identity_quality(book) > candidate_identity_quality(unique[index]):
                unique[index] = book
            continue
        positions[key] = len(unique)
        unique.append(book)
    return unique

def genre_matches(book: dict, genres: list[str]) -> bool:
    if not genres:
        return True
    text = " ".join(str(item) for item in book.get("genres", []))
    if not text:
        return False
    return any(any(alias in text for alias in GENRE_ALIASES.get(genre, (genre,))) for genre in genres)


def audience_matches(book: dict, audience: str) -> bool:
    if audience not in {"male", "female"}:
        return True
    declared = str(book.get("audience") or "").strip().lower()
    if declared in {"male", "female"}:
        return declared == audience
    # 番茄能从榜单/书库请求中取得明确频道；旧缓存或综合推荐没有频道标记时不混入。
    if str(book.get("platform") or "") == "番茄":
        return False
    category_text = " ".join(clean_html_text(str(item)) for item in (book.get("genres") or []))
    female_markers = ("女频", "现言", "古言", "宫斗", "宅斗", "豪门总裁", "青春甜宠", "女频衍生", "星光璀璨")
    male_markers = ("男频", "男频衍生", "玄幻脑洞", "都市脑洞", "都市高武", "历史古代", "东方仙侠")
    if any(marker in category_text for marker in female_markers):
        return audience == "female"
    if any(marker in category_text for marker in male_markers):
        return audience == "male"
    # 公开页没有标注频道时保留，不凭书名猜测性别频道。
    return True


def book_matches_filters(book: dict, genres: list[str], words_key: str, status_key: str) -> bool:
    if not genre_matches(book, genres):
        return False
    if words_key != "any":
        value = float(book.get("words") or 0)
        if value <= 0:
            return False
        lower, upper = WORD_LIMITS[words_key]
        if value < lower or value >= upper:
            return False
    if status_key != "all":
        value = str(book.get("status") or "")
        if status_key == "completed" and "完结" not in value:
            return False
        if status_key == "ongoing" and "连载" not in value:
            return False
    return True


def content_tags_for(book: dict) -> list[dict]:
    """根据分类和简介生成可解释的内容标签；标题单独命中永远不算严格依据。"""
    existing = book.get("contentTags")
    if isinstance(existing, list) and all(isinstance(item, dict) and item.get("name") for item in existing):
        return existing[:18]
    category = " ".join(clean_html_text(str(item)) for item in (book.get("genres") or []))
    description = clean_html_text(str(book.get("description") or ""))[:1200]
    title = clean_book_title(str(book.get("title") or ""))[:180]
    category_lower, description_lower, title_lower = category.lower(), description.lower(), title.lower()
    tags: list[dict] = []
    for name, words in CONTENT_TAG_RULES.items():
        negatives = TAG_NEGATIONS.get(name, ())
        if any(value.lower() in description_lower or value.lower() in title_lower for value in negatives):
            continue
        category_hits = [word for word in words if word.lower() in category_lower]
        description_hits = [word for word in words if word.lower() in description_lower]
        title_hits = [word for word in words if word.lower() in title_lower]
        if not (category_hits or description_hits or title_hits):
            continue
        if category_hits:
            confidence, source, evidence = 0.9, "分类", category_hits[0]
        elif description_hits:
            confidence = min(0.92, 0.68 + min(len(description_hits), 3) * 0.08)
            source, evidence = "简介", description_hits[0]
        else:
            confidence, source, evidence = 0.28, "书名", title_hits[0]
        tags.append({
            "name": name,
            "confidence": round(confidence, 2),
            "source": source,
            "evidence": evidence,
        })
    return sorted(tags, key=lambda item: (-float(item["confidence"]), item["name"]))[:18]


def enrich_content(book: dict) -> dict:
    enriched = dict(book)
    if str(enriched.get("platform") or "") == "QQ阅读":
        bid = str(enriched.get("id") or "").removeprefix("qq-")
        if bid.isdigit():
            enriched["cover"] = qq_cover_url(bid)
    # 规则升级后即时重算，避免候选池里保存的旧标签让新匹配规则失效。
    enriched.pop("contentTags", None)
    enriched["contentTags"] = content_tags_for(enriched)
    return enriched


def has_displayable_book_identity(book: dict) -> bool:
    """拒绝详情补全失败时产生的内部占位书名，避免把数字 ID 当成书推荐。"""
    title = clean_book_title(str(book.get("title") or ""))
    if not title:
        return False
    if re.fullmatch(r"番茄小说\s*\d{6,}", title):
        return False
    if re.search(r"[\ue000-\uf8ff]", title):
        return False
    return True


def content_tag_names(book: dict, strict_only: bool = False) -> set[str]:
    tags = set()
    for item in content_tags_for(book):
        if not isinstance(item, dict):
            continue
        if strict_only and (float(item.get("confidence") or 0) < 0.65 or item.get("source") == "书名"):
            continue
        tags.add(str(item.get("name") or ""))
    return tags


def subtag_match_count(available: set[str], requested: list[str]) -> int:
    return sum(1 for tag in requested if available & SUBTAG_EQUIVALENTS.get(tag, {tag}))


def subtags_match(available: set[str], requested: list[str], match_mode: str) -> bool:
    if not requested:
        return True
    hits = subtag_match_count(available, requested)
    return hits == len(requested) if match_mode == "all" else hits > 0


def book_matches_content_filters(book: dict, genres: list[str], subtags: list[str], subtag_match: str, words_key: str, status_key: str, audience: str = "all") -> bool:
    if not audience_matches(book, audience) or not book_matches_filters(book, genres, words_key, status_key):
        return False
    if not subtags:
        return True
    available = content_tag_names(book, strict_only=True)
    return subtags_match(available, subtags, subtag_match)
