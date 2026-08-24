"""跨设备同步使用的标识、令牌和书籍数据清洗。"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from mishu.sources.common import clean_book_title, clean_html_text


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError, OverflowError):
        return default


def clean_device_id(value: object) -> str:
    device_id = str(value or "").strip()
    return device_id[:120] if re.fullmatch(r"[A-Za-z0-9._:-]{8,120}", device_id) else ""


def clean_sync_device_id(value: object) -> str:
    """同步凭证用点号分段，设备 ID 不允许点号以避免 Cookie 解析歧义。"""
    device_id = clean_device_id(value)
    return device_id if device_id and "." not in device_id else ""


def secret_hash(value: str, session_secret: str) -> str:
    return hmac.new(session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def new_invite_token() -> str:
    return "mishu-sync-" + secrets.token_urlsafe(24)


def new_device_secret() -> str:
    return secrets.token_urlsafe(32)


def normalize_book(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    book_id = clean_html_text(str(raw.get("id") or ""))[:160]
    title = clean_book_title(str(raw.get("title") or ""))[:160]
    if not book_id or not title:
        return None
    genres = [clean_html_text(str(item))[:40] for item in (raw.get("genres") or [])[:12] if str(item).strip()]
    tags = []
    for item in (raw.get("contentTags") or [])[:18]:
        if not isinstance(item, dict):
            continue
        name = clean_html_text(str(item.get("name") or ""))[:40]
        if name:
            tags.append({
                "name": name,
                "confidence": max(0, min(1, safe_float(item.get("confidence")))),
                "source": clean_html_text(str(item.get("source") or ""))[:20],
                "evidence": clean_html_text(str(item.get("evidence") or ""))[:120],
            })
    return {
        "id": book_id,
        "title": title,
        "author": clean_html_text(str(raw.get("author") or "未知作者"))[:80] or "未知作者",
        "description": clean_html_text(str(raw.get("description") or ""))[:1800],
        "cover": str(raw.get("cover") or "")[:1200],
        "url": str(raw.get("url") or "")[:1200],
        "platform": clean_html_text(str(raw.get("platform") or ""))[:32],
        "genres": list(dict.fromkeys(genres)),
        "contentTags": tags,
        "words": max(0, min(10_000, safe_float(raw.get("words")))),
        "status": clean_html_text(str(raw.get("status") or ""))[:20],
    }
