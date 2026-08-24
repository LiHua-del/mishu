"""SQLite 连接与结构迁移。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

class ClosingConnection(sqlite3.Connection):
    """提交或回滚后立即关闭，避免标准 sqlite3 上下文只结束事务却遗留连接。"""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


def connect(db_file: Path, data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_file, timeout=10, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def initialize(db_lock, connect_fn) -> None:
    with db_lock, connect_fn() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL DEFAULT 'legacy',
                book_id TEXT NOT NULL,
                action TEXT NOT NULL,
                happened_at TEXT NOT NULL,
                UNIQUE(device_id, book_id, action, happened_at)
            );
            CREATE TABLE IF NOT EXISTS ai_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS discovery_candidates (
                book_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_discovery_candidates_platform_fetched
            ON discovery_candidates(platform, fetched_at DESC);
            CREATE TABLE IF NOT EXISTS rank_snapshots (
                snapshot_day TEXT NOT NULL,
                book_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                audience TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                rank_value INTEGER NOT NULL DEFAULT 0,
                popularity_score REAL NOT NULL DEFAULT 0,
                captured_at TEXT NOT NULL,
                PRIMARY KEY(snapshot_day, book_id, platform, category)
            );
            CREATE INDEX IF NOT EXISTS idx_rank_snapshots_book_day
            ON rank_snapshots(book_id, snapshot_day DESC);
            CREATE INDEX IF NOT EXISTS idx_rank_snapshots_captured
            ON rank_snapshots(captured_at);
            CREATE TABLE IF NOT EXISTS source_health (
                platform TEXT PRIMARY KEY,
                last_success_at TEXT NOT NULL,
                candidate_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS sync_spaces (
                space_id TEXT PRIMARY KEY,
                invite_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                rotated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_devices (
                space_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                device_secret_hash TEXT NOT NULL,
                device_name TEXT NOT NULL DEFAULT '',
                joined_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                revoked_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(space_id, device_id)
            );
            CREATE INDEX IF NOT EXISTS idx_sync_devices_device ON sync_devices(device_id, revoked_at);
            CREATE TABLE IF NOT EXISTS sync_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                space_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                book_id TEXT NOT NULL,
                action TEXT NOT NULL,
                happened_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                UNIQUE(space_id, event_id)
            );
            CREATE INDEX IF NOT EXISTS idx_sync_events_space_sequence ON sync_events(space_id, sequence);
            CREATE TABLE IF NOT EXISTS sync_books (
                space_id TEXT NOT NULL,
                book_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(space_id, book_id)
            );
            CREATE TABLE IF NOT EXISTS device_ai_config (
                device_id TEXT PRIMARY KEY,
                api_url TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT '',
                api_model TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            """
        )
        # 旧数据库的 events 表没有设备维度。保留已有记录为 legacy，后续新记录按设备隔离。
        event_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(events)").fetchall()}
        if "device_id" not in event_columns:
            connection.execute("ALTER TABLE events ADD COLUMN device_id TEXT NOT NULL DEFAULT 'legacy'")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_events_device_book ON events(device_id, book_id)")
        health_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(source_health)").fetchall()}
        for column, definition in (
            ("last_attempt_at", "TEXT NOT NULL DEFAULT ''"),
            ("failure_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_check_message", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in health_columns:
                connection.execute(f"ALTER TABLE source_health ADD COLUMN {column} {definition}")
        # 升级旧候选池时同步生成初始来源状态，不要求用户先触发一次全网采集。
        connection.execute(
            "INSERT INTO source_health(platform, last_success_at, candidate_count, last_error, last_attempt_at, failure_count, last_check_message) "
            "SELECT platform, MAX(fetched_at), COUNT(*), '', MAX(fetched_at), 0, '' FROM discovery_candidates GROUP BY platform "
            "ON CONFLICT(platform) DO UPDATE SET last_success_at=excluded.last_success_at, "
            "candidate_count=excluded.candidate_count, last_attempt_at=MAX(source_health.last_attempt_at, excluded.last_attempt_at)"
        )
        connection.execute("PRAGMA optimize")
