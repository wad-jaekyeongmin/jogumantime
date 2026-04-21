import os
import aiosqlite
from pathlib import Path

DATABASE_PATH = os.getenv("DATABASE_PATH", "work_bot.db")

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DATABASE_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db():
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def init_db():
    db = await get_db()
    await db.executescript(SCHEMA)
    await db.commit()


SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,            -- 'slack', 'calendar', 'jira', etc.
    source_id TEXT,                  -- 원본 ID (메시지 ts, 이벤트 id 등)
    channel_id TEXT,
    channel_name TEXT,
    sender_name TEXT,
    content TEXT NOT NULL,
    url TEXT,                        -- 딥링크
    priority_score INTEGER DEFAULT 0,
    priority_level TEXT DEFAULT 'LOW',  -- URGENT, HIGH, MEDIUM, LOW
    ai_analysis TEXT,                -- Claude AI 분석 결과
    status TEXT DEFAULT 'pending',   -- pending, notified, dismissed, snoozed
    snoozed_until TEXT,              -- ISO datetime
    batch_group TEXT,                -- 배치 그룹 ID
    created_at TEXT DEFAULT (datetime('now')),
    notified_at TEXT,
    dismissed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
CREATE INDEX IF NOT EXISTS idx_notifications_priority ON notifications(priority_level);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at);

CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,   -- Google Calendar event ID
    title TEXT NOT NULL,
    description TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    location TEXT,
    attendees TEXT,                   -- JSON array
    is_all_day INTEGER DEFAULT 0,
    synced_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON calendar_events(start_time);

CREATE TABLE IF NOT EXISTS channel_priority_overrides (
    channel_id TEXT PRIMARY KEY,
    channel_name TEXT,
    priority_level TEXT NOT NULL,    -- URGENT, HIGH, MEDIUM, LOW
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS figma_watched_files (
    file_key TEXT PRIMARY KEY,
    file_name TEXT,
    added_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS weekly_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    total_notifications INTEGER DEFAULT 0,
    urgent_count INTEGER DEFAULT 0,
    high_count INTEGER DEFAULT 0,
    medium_count INTEGER DEFAULT 0,
    low_count INTEGER DEFAULT 0,
    dismissed_count INTEGER DEFAULT 0,
    total_meeting_hours REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""
