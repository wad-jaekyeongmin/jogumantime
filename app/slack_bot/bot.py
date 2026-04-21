"""Slack Bolt 앱, 이벤트 리스너."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta

from slack_bolt.async_app import AsyncApp

from app.core.notification import (
    create_slack_notification,
    is_immediate,
    process_notification,
)
from app.db.models import NotificationStatus
from app.db.queries import update_notification_status
from app.core.briefing import generate_briefing
from app.core.weekly_report import generate_weekly_report
from app.db.queries import get_pending_notifications, get_today_events
from app.slack_bot.commands import (
    handle_briefing,
    handle_priority,
    handle_report,
    handle_schedule,
)
from app.slack_bot.dm import send_immediate_notification
from app.slack_bot.views import (
    briefing_blocks,
    priority_list_blocks,
    schedule_blocks,
    weekly_report_blocks,
)

logger = logging.getLogger(__name__)


def create_app(config: dict) -> AsyncApp:
    """Slack Bolt 앱을 생성하고 이벤트/명령어를 등록합니다."""
    app = AsyncApp(
        token=os.getenv("SLACK_BOT_TOKEN"),
        name="work-bot",
    )

    bot_user_id: str | None = None

    # ── Slack 이벤트: 메시지에서 멘션 감지 ──

    @app.event("message")
    async def handle_message(event, say, client):
        nonlocal bot_user_id

        # 봇 자신의 메시지는 무시
        if event.get("subtype") == "bot_message":
            return

        user_id = os.getenv("SLACK_USER_ID", "")
        text = event.get("text", "")
        channel = event.get("channel", "")

        # 봇 user_id 캐시
        if bot_user_id is None:
            try:
                auth = await client.auth_test()
                bot_user_id = auth["user_id"]
            except Exception:
                bot_user_id = ""

        # DM이거나 @멘션이 포함된 경우만 처리
        is_dm = channel.startswith("D")
        is_mention = f"<@{user_id}>" in text if user_id else False

        # DM에 Figma URL이 포함되면 자동 등록
        if is_dm and "figma.com/" in text:
            from app.db.queries import add_figma_file, remove_figma_file
            import re as _re
            figma_match = _re.search(r"figma\.com/(?:design|file)/([a-zA-Z0-9]+)", text)
            if figma_match:
                file_key = figma_match.group(1)
                if "삭제" in text or "제거" in text or "remove" in text.lower():
                    await remove_figma_file(file_key)
                    await say(text=f"✅ Figma 파일 감시 해제: `{file_key}`")
                else:
                    import requests as _req
                    headers = {"X-Figma-Token": os.getenv("FIGMA_API_TOKEN", "")}
                    try:
                        r = _req.get(f"https://api.figma.com/v1/files/{file_key}?depth=1", headers=headers, timeout=10)
                        fname = r.json().get("name", file_key) if r.status_code == 200 else file_key
                    except Exception:
                        fname = file_key
                    await add_figma_file(file_key, fname)
                    await say(text=f"✅ Figma 파일 감시 등록: *{fname}*\n`{file_key}`")
                return

        if not is_dm and not is_mention:
            return

        # 채널 정보
        channel_name = channel
        try:
            ch_info = await client.conversations_info(channel=channel)
            channel_name = ch_info["channel"].get("name", channel)
        except Exception:
            pass

        # 보낸이 이름
        sender_name = event.get("user", "")
        try:
            user_info = await client.users_info(user=event.get("user", ""))
            sender_name = user_info["user"].get("real_name", sender_name)
        except Exception:
            pass

        # 퍼마링크
        permalink = None
        try:
            resp = await client.chat_getPermalink(channel=channel, message_ts=event["ts"])
            permalink = resp.get("permalink")
        except Exception:
            pass

        notification = create_slack_notification(
            message_ts=event["ts"],
            channel_id=channel,
            channel_name=channel_name,
            sender_name=sender_name,
            text=text,
            permalink=permalink,
            is_mention=is_mention,
            is_dm=is_dm,
        )

        notification = await process_notification(notification, config)

        if is_immediate(notification):
            await send_immediate_notification(notification)

    # ── 슬래시 명령어 등록 ──

    @app.command("/briefing")
    async def cmd_briefing(ack, say, command):
        await handle_briefing(ack, say, command)

    @app.command("/schedule")
    async def cmd_schedule(ack, say, command):
        await handle_schedule(ack, say, command)

    @app.command("/priority")
    async def cmd_priority(ack, say, command):
        await handle_priority(ack, say, command)

    @app.command("/report")
    async def cmd_report(ack, say, command):
        await handle_report(ack, say, command)

    # ── 인터랙티브 액션 핸들러 ──

    @app.action(re.compile(r"^dismiss_(\d+)$"))
    async def handle_dismiss(ack, body, client):
        await ack()
        action_id = body["actions"][0]["action_id"]
        notification_id = int(action_id.split("_")[1])
        await update_notification_status(notification_id, NotificationStatus.DISMISSED)

        # 메시지의 블록에서 해당 알림만 취소선 처리
        try:
            blocks = body["message"].get("blocks", [])
            new_blocks = []
            dismiss_target = f"dismiss_{notification_id}"

            for block in blocks:
                # 이 블록의 액션에 dismiss 버튼이 있는지 확인
                if block.get("type") == "actions":
                    has_target = any(
                        e.get("action_id") == dismiss_target
                        for e in block.get("elements", [])
                    )
                    if has_target:
                        # 이 액션 블록을 "✅ 처리 완료"로 교체
                        new_blocks.append({
                            "type": "context",
                            "elements": [
                                {"type": "mrkdwn", "text": "✅ 처리 완료"},
                            ],
                        })
                        continue
                # 이 블록 바로 위의 section이 dismiss 대상이면 취소선
                if block.get("type") == "section":
                    accessory = block.get("accessory", {})
                    if accessory.get("action_id") == dismiss_target:
                        text = block.get("text", {}).get("text", "")
                        block = {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"~{text}~ ✅",
                            },
                        }
                new_blocks.append(block)

            await client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text="알림 업데이트",
                blocks=new_blocks,
            )
        except Exception:
            logger.exception("Failed to update dismissed message")

    @app.action(re.compile(r"^snooze_(\d+)$"))
    async def handle_snooze(ack, body, client):
        await ack()
        action_id = body["actions"][0]["action_id"]
        notification_id = int(action_id.split("_")[1])
        snoozed_until = datetime.now() + timedelta(hours=1)
        await update_notification_status(
            notification_id,
            NotificationStatus.SNOOZED,
            snoozed_until=snoozed_until,
        )

        try:
            await client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text=f"⏰ {snoozed_until.strftime('%H:%M')}에 다시 알림",
                blocks=[{
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"⏰ {snoozed_until.strftime('%H:%M')}에 다시 알림합니다.",
                    },
                }],
            )
        except Exception:
            logger.exception("Failed to update snoozed message")

    @app.action(re.compile(r"^add_cal_(\d+)$"))
    async def handle_add_calendar(ack, body, say):
        await ack()
        await say(
            text="📅 일정 추가는 `/schedule add HH:MM-HH:MM 제목` 명령어를 사용해주세요.",
        )

    @app.action("goto_thread")
    async def handle_goto_thread(ack, body):
        await ack()

    # ── App Home 탭 ──

    @app.event("app_home_opened")
    async def handle_app_home(event, client):
        user_id = event.get("user", "")
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "jogumantime"},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "업무 알림 일원화 봇 | Jira · Confluence · Figma · Calendar"},
                ],
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "오늘 브리핑"},
                        "action_id": "home_briefing",
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "대기 알림"},
                        "action_id": "home_priority",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "오늘 일정"},
                        "action_id": "home_schedule",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "주간 리포트"},
                        "action_id": "home_report",
                    },
                ],
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "*Figma 파일 감시 등록:* 이 채팅에 Figma URL을 붙여넣으세요\n*감시 해제:* URL + \"삭제\""},
                ],
            },
        ]

        try:
            await client.views_publish(
                user_id=user_id,
                view={
                    "type": "home",
                    "blocks": blocks,
                },
            )
        except Exception:
            logger.exception("Failed to publish App Home")

    # Home 버튼 액션 핸들러

    @app.action("home_briefing")
    async def handle_home_briefing(ack, body, client):
        await ack()
        data = await generate_briefing()
        blocks = briefing_blocks(data)
        user_id = body["user"]["id"]
        await client.chat_postMessage(channel=user_id, text="☀️ 오늘의 브리핑", blocks=blocks)

    @app.action("home_priority")
    async def handle_home_priority(ack, body, client):
        await ack()
        notifications = await get_pending_notifications(limit=20)
        blocks = priority_list_blocks(notifications)
        user_id = body["user"]["id"]
        await client.chat_postMessage(channel=user_id, text="🔔 대기 중인 알림", blocks=blocks)

    @app.action("home_schedule")
    async def handle_home_schedule(ack, body, client):
        await ack()
        events = await get_today_events()
        blocks = schedule_blocks(events)
        user_id = body["user"]["id"]
        await client.chat_postMessage(channel=user_id, text="📅 오늘 일정", blocks=blocks)

    @app.action("home_report")
    async def handle_home_report(ack, body, client):
        await ack()
        data = await generate_weekly_report()
        blocks = weekly_report_blocks(data)
        user_id = body["user"]["id"]
        await client.chat_postMessage(channel=user_id, text="📊 주간 리포트", blocks=blocks)

    return app
