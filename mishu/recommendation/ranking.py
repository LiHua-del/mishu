"""热门、随机、个性评分以及固定六本的来源配额。"""

from __future__ import annotations

import random

from ..config import PRIMARY_DISCOVERY_PLATFORMS, QIMAO_SUPPLEMENT_SHARE, SOURCE_SCORE_BIAS, SUBTAG_EQUIVALENTS
from ..sources.common import clean_html_text
from .content import (
    content_tag_names, enrich_content, genre_matches, has_displayable_book_identity,
    subtag_match_count, subtags_match, unique_book_candidates, book_matches_content_filters,
)

def sanitize_preference_weights(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, float] = {}
    for tag, raw_weight in list(value.items())[:48]:
        name = clean_html_text(str(tag))[:32]
        try:
            weight = max(-12.0, min(12.0, float(raw_weight)))
        except (TypeError, ValueError):
            continue
        # 详情/复制是有意保留的微弱口味证据；候选评分中的模式系数会继续限制其影响。
        if name and abs(weight) >= 0.005:
            clean[name] = weight
    return clean


def candidate_score(
    book: dict,
    genres: list[str],
    subtags: list[str],
    preference_weights: dict[str, float],
    mode: str,
) -> float:
    # 不直接把不同平台的点击榜、收藏榜和推荐榜分数横向等同；选择阶段会先换算为平台内百分位。
    popularity = max(0.0, min(100.0, float(book.get("normalizedPopularity") or book.get("popularityScore") or 0)))
    trend = max(-12.0, min(12.0, float(book.get("trendScore") or 0)))
    source_bias = SOURCE_SCORE_BIAS.get(str(book.get("platform") or ""), 0.0)
    tags = content_tag_names(book) | {str(item) for item in (book.get("genres") or [])}
    tags.add("platform:" + str(book.get("platform") or ""))
    content_score = 0.0
    if genres:
        content_score += 18.0 * sum(1 for genre in genres if genre_matches(book, [genre])) / len(genres)
    if subtags:
        content_score += 26.0 * subtag_match_count(tags, subtags) / len(subtags)
    preference = max(-24.0, min(24.0, sum(weight for tag, weight in preference_weights.items() if tag in tags)))
    freshness = 7.0 if int(book.get("rank") or 999) <= 10 else 2.5
    if mode == "popular":
        return popularity * 0.74 + content_score * 0.50 + trend * 0.85 + preference * 0.10 + freshness + source_bias
    if mode == "random":
        return content_score * 1.05 + popularity * 0.10 + trend * 0.15 + preference * 0.12 + source_bias * 0.25 + random.SystemRandom().uniform(0, 58)
    return content_score * 0.95 + popularity * 0.28 + trend * 0.50 + preference * 1.45 + freshness + source_bias * 0.65 + random.SystemRandom().uniform(0, 10)


def normalize_popularity_within_platform(books: list[dict]) -> list[dict]:
    """将各平台候选换算成平台内百分位，避免不同榜单口径互相碾压。"""
    prepared = [dict(book) for book in books]
    groups: dict[str, list[dict]] = {}
    for book in prepared:
        groups.setdefault(str(book.get("platform") or "其他"), []).append(book)
    for group in groups.values():
        group.sort(
            key=lambda book: (float(book.get("popularityScore") or 0), -int(book.get("rank") or 9999)),
            reverse=True,
        )
        total = len(group)
        for index, book in enumerate(group):
            raw = max(0.0, min(100.0, float(book.get("popularityScore") or 0)))
            if total < 3:
                normalized = raw
            else:
                percentile = 100.0 - index * 100.0 / max(1, total - 1)
                normalized = percentile * 0.72 + raw * 0.28
            book["normalizedPopularity"] = round(normalized, 2)
    return prepared


def select_six_books(
    books: list[dict], genres: list[str], subtags: list[str], subtag_match: str,
    words_key: str, status_key: str, mode: str, excluded: set[str], preference_weights: dict[str, float],
    limit: int = 6, audience: str = "all",
) -> list[dict]:
    eligible = normalize_popularity_within_platform([
        enrich_content(book) for book in unique_book_candidates(books, excluded)
        if has_displayable_book_identity(book)
        and book_matches_content_filters(enrich_content(book), genres, subtags, subtag_match, words_key, status_key, audience)
    ])
    ranked = sorted(
        eligible,
        key=lambda book: candidate_score(book, genres, subtags, preference_weights, mode),
        reverse=True,
    )
    chosen: list[dict] = []
    platform_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    requested_tags = set().union(*(SUBTAG_EQUIVALENTS.get(tag, {tag}) for tag in subtags)) if subtags else set()
    chosen_ids: set[str] = set()

    def add_book(book: dict, enforce_diversity: bool = True, platform_cap: int | None = None) -> bool:
        book_id = str(book.get("id") or "")
        if not book_id or book_id in chosen_ids or len(chosen) >= limit:
            return False
        platform = str(book.get("platform") or "其他")
        strict_tags = sorted(content_tag_names(book, strict_only=True))
        distinctive_tags = [tag for tag in strict_tags if tag not in requested_tags]
        primary_tag = distinctive_tags[0] if distinctive_tags else str((book.get("genres") or ["其他"])[0])
        author = clean_html_text(str(book.get("author") or ""))
        repeated_author = bool(author and author not in {"未知作者", "佚名"} and author_counts.get(author, 0) >= 1)
        if platform_cap is not None and platform_counts.get(platform, 0) >= platform_cap:
            return False
        if enforce_diversity and (repeated_author or tag_counts.get(primary_tag, 0) >= max(2, limit // 3)):
            return False
        chosen.append(book)
        chosen_ids.add(book_id)
        platform_counts[platform] = platform_counts.get(platform, 0) + 1
        tag_counts[primary_tag] = tag_counts.get(primary_tag, 0) + 1
        if author:
            author_counts[author] = author_counts.get(author, 0) + 1
        return True

    primary_ranked = [book for book in ranked if str(book.get("platform") or "") in PRIMARY_DISCOVERY_PLATFORMS]
    supplement_ranked = [book for book in ranked if str(book.get("platform") or "") not in PRIMARY_DISCOVERY_PLATFORMS]
    regular_supplements = [book for book in supplement_ranked if str(book.get("platform") or "") != "七猫"]
    fallback_supplements = [book for book in supplement_ranked if str(book.get("platform") or "") == "七猫"]
    available_primary = list(dict.fromkeys(str(book.get("platform") or "") for book in primary_ranked))
    primary_target = min(limit, max(1, (limit * 2 + 2) // 3)) if primary_ranked else 0
    primary_cap = primary_target if len(available_primary) == 1 else max(1, primary_target - 1)

    # 两个主来源都有候选时，各保留至少一个位置；其余仍按热度和口味得分竞争。
    for platform in available_primary:
        first = next((book for book in primary_ranked if book.get("platform") == platform), None)
        if first:
            add_book(first, enforce_diversity=False, platform_cap=primary_cap)
    for book in primary_ranked:
        if len(chosen) >= primary_target:
            break
        add_book(book, platform_cap=primary_cap)
    if len(chosen) < primary_target:
        for book in primary_ranked:
            if len(chosen) >= primary_target:
                break
            add_book(book, enforce_diversity=False, platform_cap=primary_cap)

    # 小来源最多承担约三分之一，避免平均分配稀释起点和番茄。
    supplement_target = limit - primary_target if primary_ranked else limit
    supplement_start = len(chosen)
    available_supplements = set(str(book.get("platform") or "") for book in regular_supplements)
    supplement_cap = 1 if primary_ranked and len(available_supplements) >= 2 else supplement_target
    # 七猫低频参与而非永久排除：累计约占补充位 15%，通常四到五批出现一本。
    # excluded 是当前设备近期已展示 ID，可用于偿还低频来源配额，不需要服务器保存用户画像。
    historical_qimao = sum(1 for book_id in excluded if str(book_id).startswith("qimao-"))
    completed_batches = len(excluded) // max(1, limit)
    expected_qimao = int((completed_batches + 1) * max(1, supplement_target) * QIMAO_SUPPLEMENT_SHARE)
    qimao_quota = min(1, max(0, expected_qimao - historical_qimao)) if primary_ranked else supplement_target

    def fill_supplements(queue: list[dict], target_count: int, platform_cap: int) -> None:
        for enforce_diversity in (True, False):
            for book in queue:
                if len(chosen) - supplement_start >= target_count:
                    return
                add_book(book, enforce_diversity=enforce_diversity, platform_cap=platform_cap)

    regular_goal = max(0, supplement_target - qimao_quota)
    fill_supplements(regular_supplements, regular_goal, supplement_cap)
    if qimao_quota:
        fill_supplements(fallback_supplements, supplement_target, 1 if primary_ranked else supplement_target)
    # 某一层候选不足时再由另一层补齐，保证固定六本。
    fill_supplements(regular_supplements, supplement_target, supplement_cap)
    fill_supplements(fallback_supplements, supplement_target, 1 if primary_ranked else supplement_target)

    # 某组候选不足时不留空位，继续从全体已验证候选补足六本。
    for book in ranked:
        if len(chosen) >= limit:
            break
        add_book(book, enforce_diversity=False)
    return chosen[:limit]


def prioritize_content_candidates(books: list[dict], subtags: list[str], subtag_match: str, mode: str, rng) -> list[dict]:
    """先把简介/分类已有依据的书放到详情确认队列前部，避免把请求额度耗在无关候选上。"""
    prepared = [enrich_content(book) for book in books]
    if mode == "random":
        rng.shuffle(prepared)
    if not subtags:
        return prepared
    def priority(book: dict) -> tuple[int, int, float]:
        available = content_tag_names(book, strict_only=True)
        hits = subtag_match_count(available, subtags)
        qualifies = subtags_match(available, subtags, subtag_match)
        return (1 if qualifies else 0, hits, float(book.get("popularityScore") or 0))

    prepared.sort(key=priority, reverse=True)
    return prepared
