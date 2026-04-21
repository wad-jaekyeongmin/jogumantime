"""DM 발송 (즉시 + 배치)."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from slack_sdk.web.async_client import AsyncWebClient

from app.db.models import Notification, NotificationStatus
from app.db.queries import (
    get_batch_pending_notifications,
    get_snoozed_due,
    update_notification_status,
)
from app.slack_bot.views import (
    batch_notification_blocks,
    notification_blocks,
)

logger = logging.getLogger(__name__)

_client: AsyncWebClient | None = None


def get_slack_client() -> AsyncWebClient:
    global _client
    if _client is None:
        _client = AsyncWebClient(token=os.getenv("SLACK_BOT_TOKEN"))
    return _client


def get_user_id() -> str:
    return os.getenv("SLACK_USER_ID", "")


async def send_immediate_notification(notification: Notification):
    """긴급/중요 알림을 즉시 DM으로 발송합니다."""
    client = get_slack_client()
    user_id = get_user_id()
    if not user_id:
        logger.error("SLACK_USER_ID not set")
        return

    blocks = notification_blocks(notification)
    try:
        await client.chat_postMessage(
            channel=user_id,
            text=f"[{notification.priority_level.value}] {notification.content[:100]}",
            blocks=blocks,
        )
        await update_notification_status(notification.id, NotificationStatus.NOTIFIED)
        logger.info("Sent immediate DM for notification #%s", notification.id)
    except Exception:
        logger.exception("Failed to send immediate DM")


async def flush_batch_notifications():
    """배치 대기 중인 MEDIUM/LOW 알림을 모아서 DM 발송합니다."""
    notifications = await get_batch_pending_notifications()
    if not notifications:
        return

    client = get_slack_client()
    user_id = get_user_id()
    if not user_id:
        return

    blocks = batch_notification_blocks(notifications)
    try:
        await client.chat_postMessage(
            channel=user_id,
            text=f"📬 알림 모아보기 ({len(notifications)}건)",
            blocks=blocks,
        )
        for n in notifications:
            await update_notification_status(n.id, NotificationStatus.NOTIFIED)
        logger.info("Flushed %d batch notifications", len(notifications))
    except Exception:
        logger.exception("Failed to flush batch notifications")


async def send_dm_blocks(blocks: list[dict], text: str):
    """범용 Block Kit DM 발송."""
    client = get_slack_client()
    user_id = get_user_id()
    if not user_id:
        return

    try:
        await client.chat_postMessage(
            channel=user_id,
            text=text,
            blocks=blocks,
        )
    except Exception:
        logger.exception("Failed to send DM")


async def check_and_send_snoozed():
    """스누즈 만료된 알림을 다시 발송합니다."""
    snoozed = await get_snoozed_due()
    for n in snoozed:
        n.status = NotificationStatus.PENDING
        await send_immediate_notification(n)
