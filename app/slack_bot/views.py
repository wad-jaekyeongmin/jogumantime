"""Block Kit UI 빌더."""
from __future__ import annotations

from app.db.models import Notification, PriorityLevel


PRIORITY_EMOJI = {
    PriorityLevel.URGENT: "🔴",
    PriorityLevel.HIGH: "🟠",
    PriorityLevel.MEDIUM: "🟡",
    PriorityLevel.LOW: "⚪",
}


def notification_blocks(notification: Notification) -> list[dict]:
    """단일 알림용 Block Kit 메시지."""
    emoji = PRIORITY_EMOJI.get(notification.priority_level, "⚪")
    sender = notification.sender_name or notification.source
    content = notification.content[:300]

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *[{notification.priority_level.value}]* {sender}\n{content}",
            },
        },
    ]

    if notification.ai_analysis:
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"🤖 AI: {notification.ai_analysis}"},
            ],
        })

    # 액션 버튼
    actions = {
        "type": "actions",
        "elements": [],
    }

    if notification.url:
        actions["elements"].append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Go to thread"},
            "url": notification.url,
            "action_id": "goto_thread",
        })

    actions["elements"].extend([
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Dismiss"},
            "action_id": f"dismiss_{notification.id}",
            "style": "primary",
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Snooze 1h"},
            "action_id": f"snooze_{notification.id}",
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Add to Calendar"},
            "action_id": f"add_cal_{notification.id}",
        },
    ])

    blocks.append(actions)
    blocks.append({"type": "divider"})
    return blocks


def batch_notification_blocks(notifications: list[Notification]) -> list[dict]:
    """배치 알림용 Block Kit 메시지."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📬 알림 모아보기 ({len(notifications)}건)"},
        },
    ]

    for n in notifications[:20]:
        emoji = PRIORITY_EMOJI.get(n.priority_level, "⚪")
        sender = n.sender_name or n.source
        content = n.content[:100]

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{sender}*: {content}",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Dismiss"},
                "action_id": f"dismiss_{n.id}",
            },
        })

    if len(notifications) > 20:
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"...외 {len(notifications) - 20}건"},
            ],
        })

    return blocks


def briefing_blocks(data: dict) -> list[dict]:
    """일일 브리핑 Block Kit 메시지."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"☀️ 오늘의 브리핑"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": data["date"]},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📅 오늘 일정 ({data['event_count']}건)*\n" + "\n".join(data["schedule_lines"]),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🔔 대기 알림 ({data['pending_count']}건)*\n" + "\n".join(data["notification_lines"]),
            },
        },
    ]

    return blocks


def schedule_blocks(events: list) -> list[dict]:
    """일정 보기 Block Kit 메시지."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📅 오늘 일정"},
        },
    ]

    if not events:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "오늘 예정된 일정이 없습니다."},
        })
        return blocks

    for e in events:
        start = e.start_time[11:16] if len(e.start_time) > 10 else "종일"
        end = e.end_time[11:16] if len(e.end_time) > 10 else ""
        time_str = f"{start}~{end}" if end else start
        location = f"\n📍 {e.location}" if e.location else ""

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{time_str}*  {e.title}{location}",
            },
        })

    return blocks


def priority_list_blocks(notifications: list[Notification]) -> list[dict]:
    """대기 중인 알림 + 우선순위 보기."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🔔 대기 중인 알림"},
        },
    ]

    if not notifications:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "대기 중인 알림이 없습니다."},
        })
        return blocks

    for n in notifications[:20]:
        emoji = PRIORITY_EMOJI.get(n.priority_level, "⚪")
        sender = n.sender_name or n.source
        content = n.content[:80]
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *[{n.priority_level.value}]* {sender}: {content}",
            },
        })

    return blocks


def weekly_report_blocks(data: dict) -> list[dict]:
    """주간 리포트 Block Kit 메시지."""
    stats = data["stats"]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📊 주간 리포트 ({data['week_range']})"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*🔔 알림 통계*\n"
                    f"• 총 알림: {stats['total']}건\n"
                    f"• 🔴 긴급: {stats['urgent']}건  🟠 중요: {stats['high']}건\n"
                    f"• 🟡 보통: {stats['medium']}건  ⚪ 낮음: {stats['low']}건\n"
                    f"• ✅ 처리 완료: {stats['dismissed']}건"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*📅 일정 요약*\n"
                    f"• 총 일정: {data['event_count']}건\n"
                    f"• 미팅 시간: {data['total_meeting_hours']}시간\n"
                ),
            },
        },
    ]

    if data.get("schedule_summary"):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(data["schedule_summary"][:30]),
            },
        })

    return blocks
