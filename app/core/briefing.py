"""일일 브리핑 생성."""
from __future__ import annotations

import logging
from datetime import datetime

from app.db.queries import get_pending_notifications, get_today_events

logger = logging.getLogger(__name__)


async def generate_briefing() -> dict:
    """오늘의 브리핑 데이터를 생성합니다."""
    today = datetime.now()
    events = await get_today_events()
    pending = await get_pending_notifications(limit=20)

    # 일정 포맷
    schedule_lines = []
    if events:
        for e in events:
            start = e.start_time[11:16] if len(e.start_time) > 10 else "종일"
            end = e.end_time[11:16] if len(e.end_time) > 10 else ""
            time_str = f"{start}~{end}" if end else start
            schedule_lines.append(f"• {time_str}  {e.title}")
    else:
        schedule_lines.append("• 오늘 예정된 일정이 없습니다.")

    # 대기 알림 요약
    notification_lines = []
    urgent_high = [n for n in pending if n.priority_level.value in ("URGENT", "HIGH")]
    medium_low = [n for n in pending if n.priority_level.value in ("MEDIUM", "LOW")]

    if urgent_high:
        notification_lines.append(f"🔴 긴급/중요 알림 {len(urgent_high)}건")
        for n in urgent_high[:5]:
            sender = n.sender_name or n.source
            notification_lines.append(f"  • [{n.priority_level.value}] {sender}: {n.content[:80]}")
    if medium_low:
        notification_lines.append(f"🟡 일반 알림 {len(medium_low)}건")

    if not notification_lines:
        notification_lines.append("• 대기 중인 알림이 없습니다.")

    return {
        "date": today.strftime("%Y년 %m월 %d일 %A"),
        "event_count": len(events),
        "schedule_lines": schedule_lines,
        "pending_count": len(pending),
        "urgent_high_count": len(urgent_high),
        "notification_lines": notification_lines,
    }
