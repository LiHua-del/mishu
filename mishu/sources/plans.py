"""各平台采集计划：只决定抓取入口，不参与最终推荐排序。"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote, urlencode

from ..config import *
from .fanqie import parse_fanqie_library, parse_fanqie_rank
from .qidian import parse_qidian_category_json, parse_qidian_listing, parse_qidian_rank
from .qimao import parse_qimao_discovery
from .qq_read import parse_qq_category, parse_qq_rank
from .shuqi import parse_shuqi_rank, parse_shuqi_store

def qimao_store_plans(
    genres: list[str], words_key: str, status_key: str, mode: str, rng, budget: int, audience: str = "male",
) -> list[tuple[str, object]]:
    categories: list[str] = []
    for genre in genres:
        categories.extend(QIMAO_GENRES.get(genre, ()))
    if audience == "female":
        categories = [item for item in categories if item in QIMAO_FEMALE_CATEGORIES]
        categories = list(dict.fromkeys(categories)) or ([] if genres else sorted(QIMAO_FEMALE_CATEGORIES))
    elif audience == "male":
        categories = [item for item in categories if item not in QIMAO_FEMALE_CATEGORIES]
        categories = list(dict.fromkeys(categories)) or ([] if genres else list(QIMAO_MALE_DEFAULT_CATEGORIES))
    else:
        categories = list(dict.fromkeys(categories)) or ["a"]
    if not categories:
        return []
    orders = ["click", "favorite_uv", "update_time"]
    choices: list[tuple[str, str, int]] = []
    for category in categories:
        choices.append((category, "click", 1))
    attempts = 0
    while len(choices) < budget and attempts < budget * 12:
        attempts += 1
        page = 1 + (len(choices) // max(1, len(categories))) if mode == "popular" else rng.randint(2, 16)
        order = "click" if mode == "popular" else rng.choice(orders)
        choice = (categories[len(choices) % len(categories)] if mode == "popular" else rng.choice(categories), order, page)
        if choice not in choices:
            choices.append(choice)
    words = QIMAO_WORD_BUCKETS.get(words_key, "a")
    status = QIMAO_STATUSES.get(status_key, "a")
    return [
        (
            qimao_discovery_url(category, words, status, order, page),
            lambda body, current_url, selected_order=order, selected_audience=audience: [
                {**book, "audience": selected_audience} for book in parse_qimao_discovery(body, current_url, selected_order)
            ],
        )
        for category, order, page in choices[:budget]
    ]


def qidian_rank_plans(genres: list[str], words_key: str, status_key: str, mode: str, rng, budget: int, audience: str = "male") -> list[tuple[str, object]]:
    if audience == "female":
        return []
    categories = list(dict.fromkeys(QIDIAN_GENRES[genre] for genre in genres if genre in QIDIAN_GENRES)) or [""]
    if words_key in {"under30", "30to50"}:
        rank_kinds = ["newbook", "update", "newauthor", "newfans", "rec", "yuepiao"]
    elif status_key == "completed" or words_key == "over200":
        rank_kinds = ["hotsales", "readindex", "yuepiao", "rec", "newfans"]
    else:
        rank_kinds = ["yuepiao", "hotsales", "readindex", "newfans", "rec", "update", "sign", "newbook"]
    choices = [(category, rank_kind) for category in categories[:3] for rank_kind in rank_kinds]
    if mode == "random":
        rng.shuffle(choices)
    month = datetime.now().strftime("%Y%m")
    plans: list[tuple[str, object]] = []
    for category, rank_kind in choices[:budget]:
        category_path = f"catid{category}/" if category else ""
        url = f"https://m.qidian.com/rank/{rank_kind}/{category_path}{month}/"
        plans.append((url, parse_qidian_rank))
    return plans


def qidian_store_plans(genres: list[str], words_key: str, status_key: str, mode: str, rng, budget: int, audience: str = "male") -> list[tuple[str, object, str]]:
    categories = list(dict.fromkeys(QIDIAN_GENRES[genre] for genre in genres if genre in QIDIAN_GENRES)) or ["-1"]
    choices: list[tuple[str, int]] = []
    for category in categories[:budget]:
        choices.append((category, 1))
    attempts = 0
    while len(choices) < budget and attempts < budget * 12:
        attempts += 1
        page_num = 1 + len(choices) // max(1, len(categories)) if mode == "popular" else rng.randint(2, 40)
        category = categories[len(choices) % len(categories)] if mode == "popular" else rng.choice(categories)
        choice = (category, page_num)
        if choice not in choices:
            choices.append(choice)
    plans: list[tuple[str, object, str]] = []
    for category, page_num in choices[:budget]:
        params = {"catId": category, "pageNum": str(page_num), "gender": "female" if audience == "female" else "male"}
        word_value = QIDIAN_WORD_BUCKETS.get(words_key, "")
        status_value = QIDIAN_STATUSES.get(status_key, "")
        if word_value:
            params["size"] = word_value
        if status_value:
            params["isfinish"] = status_value
        url = "https://m.qidian.com/webcommon/category/list?" + urlencode(params)
        referer = f"https://m.qidian.com/category/catid{category}/" if category != "-1" else "https://m.qidian.com/category/"
        label = next((genre for genre, cat_id in QIDIAN_GENRES.items() if cat_id == category), "全部")
        parser = lambda payload, category_label=label, selected_page=page_num: parse_qidian_category_json(payload, category_label, selected_page, "")
        plans.append((url, parser, referer))
    return plans


def qidian_listing_plans(genres: list[str], subtags: list[str], budget: int, audience: str = "male") -> list[tuple[str, object]]:
    if audience == "female":
        return []
    plans: list[tuple[str, object]] = []
    categories = list(dict.fromkeys(QIDIAN_GENRES[genre] for genre in genres if genre in QIDIAN_GENRES))
    for category in categories[:3]:
        plans.append((f"https://m.qidian.com/category/catid{category}/", parse_qidian_listing))
    search_terms: list[str] = []
    for subtag in list(dict.fromkeys(subtags))[:4]:
        equivalents = sorted(SUBTAG_EQUIVALENTS.get(subtag, {subtag}) - {subtag})
        search_terms.extend((subtag, *equivalents, *CONTENT_TAG_RULES.get(subtag, ())[:4]))
    for term in list(dict.fromkeys(search_terms)):
        url = f"https://m.qidian.com/soushu/{quote(term)}.html"
        plans.append((url, lambda body, current_url, label=term: parse_qidian_listing(body, current_url, f"内容检索·{label}")))
    return plans[:budget]


def fanqie_library_plans(genres: list[str], words_key: str, status_key: str, mode: str, rng, budget: int, audience: str = "male") -> list[tuple[str, object, str]]:
    categories: list[tuple[str, str, str]] = []
    for genre in genres:
        categories.extend(FANQIE_GENRES.get(genre, ()))
    if not categories:
        categories = [
            ("1", "257", "玄幻脑洞"), ("1", "261", "都市日常"), ("1", "1140", "东方仙侠"),
            ("1", "8", "科幻末世"), ("0", "267", "现言脑洞"), ("0", "1139", "古风世情"),
        ]
    categories = list(dict.fromkeys(categories))
    gender_code = "0" if audience == "female" else "1"
    if audience in {"male", "female"}:
        categories = [item for item in categories if item[0] == gender_code]
    if not categories:
        return []
    choices: list[tuple[str, str, str, int, str]] = []
    for gender, category_id, label in categories[:budget]:
        choices.append((gender, category_id, label, 0, "0"))
    attempts = 0
    while len(choices) < budget and attempts < budget * 12:
        attempts += 1
        gender, category_id, label = categories[len(choices) % len(categories)] if mode == "popular" else rng.choice(categories)
        page_index = len(choices) // max(1, len(categories)) if mode == "popular" else rng.randint(1, 12)
        sort_value = "0" if mode == "popular" else rng.choice(("0", "1"))
        choice = (gender, category_id, label, page_index, sort_value)
        if choice not in choices:
            choices.append(choice)
    plans: list[tuple[str, object, str]] = []
    for gender, category_id, label, page_index, sort_value in choices[:budget]:
        query = urlencode({
            "page_count": "18", "page_index": str(page_index), "gender": gender,
            "category_id": category_id, "creation_status": FANQIE_STATUSES.get(status_key, "-1"),
            "word_count": FANQIE_WORD_BUCKETS.get(words_key, "-1"), "book_type": "-1", "sort": sort_value,
        })
        url = "https://fanqienovel.com/api/author/library/book_list/v0/?" + query
        parser = lambda payload, category_label=label, selected_page=page_index, selected_sort=sort_value, selected_gender=gender: [
            {**book, "audience": "female" if selected_gender == "0" else "male"}
            for book in parse_fanqie_library(payload, category_label, selected_page, selected_sort)
        ]
        plans.append((url, parser, "https://fanqienovel.com/library/"))
    return plans


def fanqie_rank_plans(genres: list[str], words_key: str, mode: str, rng, budget: int, audience: str = "male", rank_categories=None) -> list[tuple[str, object]]:
    categories: list[tuple[str, str, str]] = []
    for genre in genres:
        categories.extend(FANQIE_GENRES.get(genre, ()))
    if not categories:
        categories = rank_categories() if rank_categories else []
    if not categories:
        for genre in ("玄幻", "都市", "仙侠", "科幻", "悬疑灵异", "历史", "言情", "N次元"):
            categories.extend(FANQIE_GENRES.get(genre, ())[:2])
    categories = list(dict.fromkeys(categories))
    gender_code = "0" if audience == "female" else "1"
    if audience in {"male", "female"}:
        categories = [item for item in categories if item[0] == gender_code]
    if mode in {"random", "mixed"}:
        rng.shuffle(categories)

    rank_types = ["1"] if words_key == "under30" else (["2", "1"] if words_key == "any" else ["2"])
    candidates: list[tuple[str, str, str, str]] = []
    for gender, category_id, label in categories:
        for rank_type in rank_types:
            candidates.append((gender, rank_type, category_id, label))
    if mode == "random":
        rng.shuffle(candidates)
    selected = candidates[:budget]
    return [
        (
            f"https://fanqienovel.com/rank/{gender}_{rank_type}_{category_id}",
            lambda body, current_url, category_label=label, selected_gender=gender: [
                {**book, "audience": "female" if selected_gender == "0" else "male"}
                for book in parse_fanqie_rank(body, current_url, category_label)
            ],
        )
        for gender, rank_type, category_id, label in selected
    ]

def shuqi_store_plans(genres: list[str], words_key: str, status_key: str, mode: str, rng, budget: int) -> list[tuple[str, object]]:
    categories: list[str] = []
    for genre in genres:
        categories.extend(SHUQI_STORE_GENRES.get(genre, ()))
    categories = list(dict.fromkeys(categories)) or ["0"]
    choices: list[tuple[str, int]] = []
    if mode == "popular":
        page = 1
        while len(choices) < budget:
            for category in categories:
                choices.append((category, page))
                if len(choices) >= budget:
                    break
            page += 1
    else:
        # 每个分类先读第一页，再随机探索更深分页，兼顾热门和新鲜度。
        choices.extend((category, 1) for category in categories[:budget])
        attempts = 0
        while len(choices) < budget and attempts < budget * 10:
            attempts += 1
            choice = (rng.choice(categories), rng.randint(2, 18))
            if choice not in choices:
                choices.append(choice)
    plans: list[tuple[str, object]] = []
    for category, page in choices:
        query = urlencode({
            "sz": "0",
            "fc": category,
            "wd": SHUQI_STORE_WORDS.get(words_key, "10"),
            "tm": "0",
            "st": SHUQI_STORE_STATUSES.get(status_key, "0"),
            "page": str(page),
        })
        plans.append((f"https://ognv.shuqi.com/store?{query}", parse_shuqi_store))
    return plans


def shuqi_rank_plans(words_key: str, status_key: str, mode: str, rng, budget: int, audience: str = "male") -> list[tuple[str, object]]:
    if status_key == "completed":
        rank_kinds = ["allEnd", "boyEnd", "girlEnd"]
    elif words_key == "under30":
        rank_kinds = ["boyUpdate", "girlUpdate", "boyClick", "girlClick", "allClick", "allStore", "boyhot", "girlhot"]
    else:
        rank_kinds = ["allClick", "allStore", "allOrder", "boyClick", "girlClick", "boyStore", "girlStore", "boyOrder", "girlOrder", "boyhot", "girlhot", "allWords"]

    if audience == "male":
        rank_kinds = [kind for kind in rank_kinds if not kind.startswith("girl") and kind != "allClick" and kind != "allStore" and kind != "allOrder" and kind != "allEnd" and kind != "allWords"] or ["boyClick", "boyStore", "boyhot"]
    elif audience == "female":
        rank_kinds = [kind for kind in rank_kinds if not kind.startswith("boy") and kind != "allClick" and kind != "allStore" and kind != "allOrder" and kind != "allEnd" and kind != "allWords"] or ["girlClick", "girlStore", "girlhot"]
    choices: list[tuple[str, int]] = []
    if mode == "popular":
        page = 1
        while len(choices) < budget:
            for rank_kind in rank_kinds:
                choices.append((rank_kind, page))
                if len(choices) >= budget:
                    break
            page += 1
    else:
        popular_count = min(3, budget) if mode == "mixed" else 0
        choices.extend((rank_kind, 1) for rank_kind in rank_kinds[:popular_count])
        attempts = 0
        while len(choices) < budget and attempts < budget * 8:
            attempts += 1
            choice = (rng.choice(rank_kinds), rng.randint(1, 20))
            if choice not in choices:
                choices.append(choice)
    return [
        (
            f"https://ognv.shuqi.com/ranklist?rank={rank_kind}&page={page}",
            lambda body, current_url, selected_kind=rank_kind: parse_shuqi_rank(body, current_url, selected_kind),
        )
        for rank_kind, page in choices
    ]


def qq_rank_plans(genres: list[str], words_key: str, status_key: str, mode: str, rng, budget: int, audience: str = "male") -> list[tuple[str, object]]:
    if audience == "female":
        genders = ["female"]
    elif audience == "male":
        genders = ["male"]
    elif genres and all(genre == "言情" for genre in genres):
        genders = ["female"]
    elif not genres or "言情" in genres:
        genders = ["male", "female"]
    else:
        genders = ["male"]

    if status_key == "completed":
        rank_kinds = ["finish"]
    elif words_key == "under30":
        rank_kinds = ["new", "free", "sell"]
    else:
        rank_kinds = ["sell", "new", "free", "god", "finish"]

    choices: list[tuple[str, str, int]] = []
    if mode == "popular":
        page = 1
        while len(choices) < budget:
            for gender in genders:
                for rank_kind in rank_kinds:
                    choices.append((gender, rank_kind, page))
                    if len(choices) >= budget:
                        break
                if len(choices) >= budget:
                    break
            page += 1
    else:
        popular_count = min(2, budget) if mode == "mixed" else 0
        choices.extend((genders[index % len(genders)], rank_kinds[index % len(rank_kinds)], 1) for index in range(popular_count))
        attempts = 0
        while len(choices) < budget and attempts < budget * 8:
            attempts += 1
            choice = (rng.choice(genders), rng.choice(rank_kinds), rng.randint(1, 10))
            if choice not in choices:
                choices.append(choice)

    plans: list[tuple[str, object]] = []
    for gender, rank_kind, page in choices:
        cycle = "5" if rank_kind == "sell" else "1"
        suffix = "" if page == 1 else f"-{page}"
        url = f"https://book.qq.com/book-rank/{gender}-{rank_kind}/cycle-{cycle}{suffix}"
        plans.append((url, lambda body, current_url, selected_kind=rank_kind: parse_qq_rank(body, current_url, selected_kind)))
    return plans


def qq_category_plans(genres: list[str], words_key: str, status_key: str, mode: str, rng, budget: int) -> list[tuple[str, object]]:
    categories: list[str] = []
    for genre in genres:
        categories.extend(QQ_CATEGORIES.get(genre, ()))
    categories = list(dict.fromkeys(categories)) or ["0"]
    word_values = QQ_WORD_BUCKETS.get(words_key, ("0",))
    status_value = QQ_STATUSES.get(status_key, "0")
    sort_values = ["0", "1", "2"] if mode == "popular" else ["0", "1", "2", "3"]
    combinations = [(category, word_value) for category in categories for word_value in word_values]
    choices: list[tuple[str, str, str, int]] = []
    if mode == "random":
        attempts = 0
        while len(choices) < budget and attempts < budget * 12:
            attempts += 1
            category, word_value = rng.choice(combinations)
            choice = (category, word_value, rng.choice(sort_values), rng.randint(2, 16))
            if choice not in choices:
                choices.append(choice)
    else:
        page = 1
        while len(choices) < budget:
            for index, (category, word_value) in enumerate(combinations):
                sort_value = sort_values[(page - 1 + index) % len(sort_values)]
                choices.append((category, word_value, sort_value, page))
                if len(choices) >= budget:
                    break
            page += 1
    return [
        (
            f"https://book.qq.com/book-cate/{category}-0-{status_value}-0-{word_value}-0-{sort_value}-{page}",
            parse_qq_category,
        )
        for category, word_value, sort_value, page in choices[:budget]
    ]

def qimao_discovery_url(category: str, words: str, status: str, order: str, page: int) -> str:
    return f"https://www.qimao.com/shuku/a-{category}-a-{words}-a-a-{status}-{order}-{page}/"
