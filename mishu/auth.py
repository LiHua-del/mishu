"""访问口令会话与登录失败限流。"""

import base64
import hashlib
import hmac
import threading
import time

from .config import MISHU_SESSION_DAYS, MISHU_SESSION_SECRET


AUTH_LOCK = threading.Lock()
AUTH_FAILURES: dict[str, list[float]] = {}


def session_token(expiry: int | None = None) -> str:
    expires_at = expiry or int(time.time()) + MISHU_SESSION_DAYS * 86400
    payload = str(expires_at)
    signature = hmac.new(MISHU_SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{payload}.{encoded}"


def valid_session_token(value: str) -> bool:
    try:
        payload, signature = value.split(".", 1)
        expiry = int(payload)
    except (ValueError, TypeError):
        return False
    if expiry < int(time.time()):
        return False
    expected = session_token(expiry).split(".", 1)[1]
    return hmac.compare_digest(signature, expected)


def auth_attempt_allowed(address: str) -> bool:
    now_value = time.monotonic()
    with AUTH_LOCK:
        recent = [value for value in AUTH_FAILURES.get(address, []) if now_value - value < 600]
        AUTH_FAILURES[address] = recent
        return len(recent) < 8


def record_auth_failure(address: str) -> None:
    with AUTH_LOCK:
        AUTH_FAILURES.setdefault(address, []).append(time.monotonic())


def clear_auth_failures(address: str) -> None:
    with AUTH_LOCK:
        AUTH_FAILURES.pop(address, None)
