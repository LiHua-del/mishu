"""统一时间格式，避免平台快照与数据库记录各自计算。"""

from datetime import datetime, timedelta, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def china_day() -> str:
    """平台榜单按中国时区分日，避免午夜附近把同一天拆成两个快照。"""
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()
