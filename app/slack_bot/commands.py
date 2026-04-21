"""슬래시 명령어 핸들러: /briefing, /schedule, /priority, /report."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from slack_bolt.async_app import AsyncAck, AsyncSay

from app.core.briefing import generate_briefing
from app.core.weekly_report import generate_weekly_report
from app.db.models import PriorityLevel
from app.db.queries import (
    get_pending_notifications,
    get_today_events,
    set_channel_priority,
)
from app.integrations.google_calendar import create_calendar_event
from app.slack_bot.views import (
    briefing_blocks,
    priority_list_blocks,
    schedule_blocks,
    weekly_report_blocks,
)

logger = logging.getLogger(__name__)


async def handle_briefing(ack: AsyncAck, say: AsyncSay, command: dict):
    """/briefing - 브리핑 즉시 생성."""
    await ack()
    data = await generate_briefing()
    blocks = briefing_blocks(data)
    await say(text="☀️ 오늘의 브리핑", blocks=blocks)


async def handle_schedule(ack: AsyncAck, say: AsyncSay, command: dict):
    """/schedule - 오늘 일정 보기 또는 일정 추가."""
    await ack()
    text = command.get("text", "").strip()

    if text.startswith("add "):
        await _handle_schedule_add(say, text[4:].strip())
    else:
        events = await get_today_events()
        blocks = schedule_blocks(events)
        await say(text="📅 오늘 일정", blocks=blocks)


async def _handle_schedule_add(say: AsyncSay, text: str):
    """일정 추가: /schedule add 14:00-15:00 디자인 리뷰."""
    # 패턴: HH:MM-HH:MM 제목
    match = re.match(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})\s+(.+)", text)
    if not match:
        await say(text="⚠️ 형식: `/schedule add 14:00-15:00 디자인 리뷰`")
        return

    start_str, end_str, title = match.groups()
    today = datetime.now().strftime("%Y-%m-%d")

    start_time = f"{today}T{start_str}:00+09:00"
    end_time = f"{today}T{end_str}:00+09:00"

    link = await create_calendar_event(title, start_time, end_time)
    if link:
        await say(text=f"✅ 일정 추가 완료: *{title}* ({start_str}~{end_str})\n<{link}|캘린더에서 보기>")
    else:
        await say(text="❌ 일정 추가에 실패했습니다.")


async def handle_priority(ack: AsyncAck, say: AsyncSay, command: dict):
    """/priority - 대기 중인 알림 보기 또는 채널 우선순위 설정."""
    await ack()
    text = command.get("text", "").strip()

    if text.startswith("set "):
        await _handle_priority_set(say, text[4:].strip())
    else:
        notifications = await get_pending_notifications(limit=20)
        blocks = priority_list_blocks(notifications)
        await say(text="🔔 대기 중인 알림", blocks=blocks)


async def _handle_priority_set(say: AsyncSay, text: str):
    """채널 우선순위 설정: /priority set #channel-name HIGH."""
    parts = text.split()
    if len(parts) < 2:
        await say(text="⚠️ 형식: `/priority set #channel-name HIGH`")
        return

    channel_ref = parts[0]
    level_str = parts[1].upper()

    if level_str not in PriorityLevel.__members__:
        await say(text=f"⚠️ 유효한 우선순위: URGENT, HIGH, MEDIUM, LOW")
        return

    # #channel-name 또는 <#C123|channel-name> 처리
    channel_id = channel_ref
    channel_name = channel_ref.lstrip("#")
    match = re.match(r"<#(\w+)\|?([^>]*)>", channel_ref)
    if match:
        channel_id = match.group(1)
        channel_name = match.group(2) or channel_id

    level = PriorityLevel(level_str)
    await set_channel_priority(channel_id, channel_name, level)
    await say(text=f"✅ *{channel_name}* 채널 우선순위를 *{level.value}*로 설정했습니다.")


async def handle_report(ack: AsyncAck, say: AsyncSay, command: dict):
    """/report - 주간 리포트 즉시 생성."""
    await ack()
    data = await generate_weekly_report()
    blocks = weekly_report_blocks(data)
    await say(text="📊 주간 리포트", blocks=blocks)
