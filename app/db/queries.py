from __future__ import annotations

from datetime import datetime, timedelta

from app.db.database import get_db
from app.db.models import (
    CalendarEvent,
    Notification,
    NotificationStatus,
    PriorityLevel,
)


# ── Notifications ──


async def insert_notification(n: Notification) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO notifications
           (source, source_id, channel_id, channel_name, sender_name,
            content, url, priority_score, priority_level, ai_analysis,
            status, snoozed_until, batch_group)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            n.source, n.source_id, n.channel_id, n.channel_name,
            n.sender_name, n.content, n.url, n.priority_score,
            n.priority_level.value, n.ai_analysis, n.status.value,
            n.snoozed_until, n.batch_group,
        ),
    )
    await db.commit()
    return cursor.lastrowid


async def get_pending_notifications(
    limit: int = 50,
) -> list[Notification]:
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT * FROM notifications
           WHERE status = 'pending'
           ORDER BY priority_score DESC, created_at ASC
           LIMIT ?""",
        (limit,),
    )
    return [Notification.from_row(r) for r in rows]


async def get_batch_pending_notifications() -> list[Notification]:
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT * FROM notifications
           WHERE status = 'pending'
             AND priority_level IN ('MEDIUM', 'LOW')
           ORDER BY priority_score DESC, created_at ASC""",
    )
    return [Notification.from_row(r) for r in rows]


async def get_snoozed_due() -> list[Notification]:
    db = await get_db()
    now = datetime.now().isoformat()
    rows = await db.execute_fetchall(
        """SELECT * FROM notifications
           WHERE status = 'snoozed' AND snoozed_until <= ?
           ORDER BY priority_score DESC""",
        (now,),
    )
    return [Notification.from_row(r) for r in rows]


async def update_notification_status(
    notification_id: int,
    status: NotificationStatus,
    **kwargs,
):
    db = await get_db()
    sets = ["status = ?"]
    params: list = [status.value]

    if status == NotificationStatus.NOTIFIED:
        sets.append("notified_at = ?")
        params.append(datetime.now().isoformat())
    elif status == NotificationStatus.DISMISSED:
        sets.append("dismissed_at = ?")
        params.append(datetime.now().isoformat())
    elif status == NotificationStatus.SNOOZED and "snoozed_until" in kwargs:
        sets.append("snoozed_until = ?")
        params.append(kwargs["snoozed_until"].isoformat())

    params.append(notification_id)
    await db.execute(
        f"UPDATE notifications SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    await db.commit()


async def get_notification_stats(since: datetime) -> dict:
    db = await get_db()
    row = await db.execute_fetchall(
        """SELECT
             COUNT(*) as total,
             SUM(CASE WHEN priority_level='URGENT' THEN 1 ELSE 0 END) as urgent,
             SUM(CASE WHEN priority_level='HIGH' THEN 1 ELSE 0 END) as high,
             SUM(CASE WHEN priority_level='MEDIUM' THEN 1 ELSE 0 END) as medium,
             SUM(CASE WHEN priority_level='LOW' THEN 1 ELSE 0 END) as low,
             SUM(CASE WHEN status='dismissed' THEN 1 ELSE 0 END) as dismissed
           FROM notifications
           WHERE created_at >= ?""",
        (since.isoformat(),),
    )
    r = row[0]
    return {
        "total": r["total"] or 0,
        "urgent": r["urgent"] or 0,
        "high": r["high"] or 0,
        "medium": r["medium"] or 0,
        "low": r["low"] or 0,
        "dismissed": r["dismissed"] or 0,
    }


async def check_duplicate(source: str, source_id: str) -> bool:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT 1 FROM notifications WHERE source = ? AND source_id = ? LIMIT 1",
        (source, source_id),
    )
    return len(rows) > 0


# ── Calendar Events ──


async def upsert_calendar_event(e: CalendarEvent):
    db = await get_db()
    await db.execute(
        """INSERT INTO calendar_events
           (event_id, title, description, start_time, end_time,
            location, attendees, is_all_day, synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(event_id) DO UPDATE SET
             title=excluded.title,
             description=excluded.description,
             start_time=excluded.start_time,
             end_time=excluded.end_time,
             location=excluded.location,
             attendees=excluded.attendees,
             is_all_day=excluded.is_all_day,
             synced_at=datetime('now')""",
        (
            e.event_id, e.title, e.description, e.start_time,
            e.end_time, e.location, e.attendees, int(e.is_all_day),
        ),
    )
    await db.commit()


async def get_today_events() -> list[CalendarEvent]:
    db = await get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = await db.execute_fetchall(
        """SELECT * FROM calendar_events
           WHERE start_time >= ? AND start_time < ?
           ORDER BY start_time ASC""",
        (today, tomorrow),
    )
    return [CalendarEvent.from_row(r) for r in rows]


async def get_week_events() -> list[CalendarEvent]:
    db = await get_db()
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    rows = await db.execute_fetchall(
        """SELECT * FROM calendar_events
           WHERE start_time >= ? AND start_time < ?
           ORDER BY start_time ASC""",
        (monday.strftime("%Y-%m-%d"), (sunday + timedelta(days=1)).strftime("%Y-%m-%d")),
    )
    return [CalendarEvent.from_row(r) for r in rows]


# ── Channel Priority Overrides ──


async def set_channel_priority(
    channel_id: str, channel_name: str, priority_level: PriorityLevel,
):
    db = await get_db()
    await db.execute(
        """INSERT INTO channel_priority_overrides (channel_id, channel_name, priority_level)
           VALUES (?, ?, ?)
           ON CONFLICT(channel_id) DO UPDATE SET
             channel_name=excluded.channel_name,
             priority_level=excluded.priority_level,
             updated_at=datetime('now')""",
        (channel_id, channel_name, priority_level.value),
    )
    await db.commit()


async def add_figma_file(file_key: str, file_name: str = ""):
    db = await get_db()
    await db.execute(
        """INSERT INTO figma_watched_files (file_key, file_name)
           VALUES (?, ?)
           ON CONFLICT(file_key) DO UPDATE SET file_name=excluded.file_name""",
        (file_key, file_name),
    )
    await db.commit()


async def remove_figma_file(file_key: str):
    db = await get_db()
    await db.execute("DELETE FROM figma_watched_files WHERE file_key = ?", (file_key,))
    await db.commit()


async def get_figma_watched_files() -> list[str]:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT file_key FROM figma_watched_files")
    return [r["file_key"] for r in rows]


async def get_channel_priority(channel_id: str) -> PriorityLevel | None:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT priority_level FROM channel_priority_overrides WHERE channel_id = ?",
        (channel_id,),
    )
    if rows:
        return PriorityLevel(rows[0]["priority_level"])
    return None
