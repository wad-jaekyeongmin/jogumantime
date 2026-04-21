"""알림 모델 + 처리 파이프라인."""
from __future__ import annotations

import logging
from datetime import datetime

from app.db.models import Notification, NotificationStatus, PriorityLevel
from app.db.queries import check_duplicate, insert_notification
from app.core.priority import score_notification

logger = logging.getLogger(__name__)


def create_slack_notification(
    *,
    message_ts: str,
    channel_id: str,
    channel_name: str,
    sender_name: str,
    text: str,
    permalink: str | None = None,
    is_mention: bool = False,
    is_dm: bool = False,
) -> Notification:
    return Notification(
        source="slack",
        source_id=message_ts,
        channel_id=channel_id,
        channel_name=channel_name,
        sender_name=sender_name,
        content=text,
        url=permalink,
    )


def create_calendar_notification(
    *,
    event_id: str,
    title: str,
    start_time: str,
    minutes_until: int,
) -> Notification:
    content = f"📅 곧 시작: {title} ({minutes_until}분 후, {start_time})"
    return Notification(
        source="calendar",
        source_id=f"cal-reminder-{event_id}",
        content=content,
    )


async def process_notification(
    notification: Notification,
    config: dict,
) -> Notification:
    """알림 처리 파이프라인: 중복 확인 → 스코어링 → 저장."""
    if notification.source_id:
        if await check_duplicate(notification.source, notification.source_id):
            logger.debug("Duplicate notification: %s/%s", notification.source, notification.source_id)
            return notification

    notification = await score_notification(notification, config)

    notification.id = await insert_notification(notification)
    logger.info(
        "Processed notification #%s: %s [%s] score=%d",
        notification.id,
        notification.source,
        notification.priority_level.value,
        notification.priority_score,
    )
    return notification


def create_jira_notification(
    *,
    issue_key: str,
    issue_summary: str,
    event_type: str,
    author: str | None = None,
    body: str | None = None,
    url: str | None = None,
    comment_id: str | None = None,
) -> Notification:
    """Jira 댓글/멘션 알림 생성."""
    if event_type == "comment":
        content = f"💬 [{issue_key}] {issue_summary}\n{author}: {body}"
    else:
        content = f"📌 [{issue_key}] {issue_summary}\n멘션됨"

    sid = comment_id or f"{issue_key}-{hash((body or '') + (author or ''))}"
    return Notification(
        source="jira",
        source_id=f"jira-{event_type}-{sid}",
        channel_name=issue_key,
        sender_name=author or "Jira",
        content=content,
        url=url,
    )


def create_confluence_notification(
    *,
    page_title: str,
    event_type: str,
    author: str | None = None,
    body: str | None = None,
    url: str | None = None,
) -> Notification:
    """Confluence 댓글/멘션 알림 생성."""
    if event_type == "comment":
        content = f"💬 [Confluence] {page_title}\n{author}: {body}"
    else:
        content = f"📌 [Confluence] {page_title}\n멘션됨"

    sid = f"{hash((page_title or '') + (author or '') + (body or ''))}"
    return Notification(
        source="confluence",
        source_id=f"conf-{event_type}-{sid}",
        channel_name="confluence",
        sender_name=author or "Confluence",
        content=content,
        url=url,
    )


def create_figma_notification(
    *,
    file_name: str,
    event_type: str,
    author: str | None = None,
    body: str | None = None,
    url: str | None = None,
) -> Notification:
    """Figma 댓글/멘션 알림 생성."""
    if event_type == "comment":
        content = f"💬 [Figma] {file_name}\n{author}: {body}"
    else:
        content = f"📌 [Figma] {file_name}\n멘션됨: {body}"

    sid = f"{hash((file_name or '') + (author or '') + (body or ''))}"
    return Notification(
        source="figma",
        source_id=f"figma-{event_type}-{sid}",
        channel_name="figma",
        sender_name=author or "Figma",
        content=content,
        url=url,
    )


def is_immediate(notification: Notification) -> bool:
    """즉시 알림 대상인지 판단."""
    return notification.priority_level in (PriorityLevel.URGENT, PriorityLevel.HIGH)
