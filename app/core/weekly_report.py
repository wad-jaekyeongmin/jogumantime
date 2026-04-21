"""주간 리포트 생성."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.db.queries import get_notification_stats, get_week_events

logger = logging.getLogger(__name__)


async def generate_weekly_report() -> dict:
    """이번 주 업무 통계 리포트를 생성합니다."""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)

    # 이번 주 알림 통계
    stats = await get_notification_stats(since=monday)

    # 이번 주 일정 분석
    events = await get_week_events()
    total_meeting_hours = 0.0
    meetings_by_day: dict[str, list[str]] = {}

    for e in events:
        if e.is_all_day:
            continue
        try:
            start = datetime.fromisoformat(e.start_time)
            end = datetime.fromisoformat(e.end_time)
            hours = (end - start).total_seconds() / 3600
            total_meeting_hours += hours

            day_key = start.strftime("%m/%d(%a)")
            meetings_by_day.setdefault(day_key, [])
            time_range = f"{start.strftime('%H:%M')}~{end.strftime('%H:%M')}"
            meetings_by_day[day_key].append(f"{time_range} {e.title}")
        except (ValueError, TypeError):
            continue

    # 일정 요약
    schedule_summary = []
    for day, meetings in sorted(meetings_by_day.items()):
        schedule_summary.append(f"*{day}*")
        for m in meetings:
            schedule_summary.append(f"  • {m}")

    return {
        "week_range": f"{monday.strftime('%m/%d')}~{friday.strftime('%m/%d')}",
        "stats": stats,
        "total_meeting_hours": round(total_meeting_hours, 1),
        "event_count": len(events),
        "schedule_summary": schedule_summary,
    }
