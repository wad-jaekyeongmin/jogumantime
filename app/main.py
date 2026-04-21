"""진입점: Slack Bot + FastAPI + Scheduler를 단일 프로세스에서 실행."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import uvicorn
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

from app.api.routes import router as api_router
from app.core.briefing import generate_briefing
from app.core.scheduler import setup_scheduler, scheduler
from app.core.weekly_report import generate_weekly_report
from app.db.database import close_db, init_db
from app.integrations.google_calendar import sync_today_events
from app.integrations.jira import poll_jira_comments, poll_jira_mentions
from app.integrations.confluence import poll_confluence_comments, poll_confluence_mentions
from app.integrations.figma import poll_figma_comments
from app.slack_bot.bot import create_app as create_slack_app
from app.slack_bot.dm import (
    check_and_send_snoozed,
    flush_batch_notifications,
    send_dm_blocks,
)
from app.slack_bot.views import briefing_blocks, weekly_report_blocks

# ── 로깅 설정 ──

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Config 로딩 ──

def load_config() -> dict:
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    logger.warning("config.yaml not found, using defaults")
    return {}


# ── 스케줄 작업 정의 ──

config = load_config()


async def job_daily_briefing():
    """일일 브리핑 자동 발송."""
    logger.info("Running daily briefing job")
    data = await generate_briefing()
    blocks = briefing_blocks(data)
    await send_dm_blocks(blocks, "☀️ 오늘의 브리핑")


async def job_batch_flush():
    """배치 알림 플러시."""
    logger.info("Running batch flush job")
    await flush_batch_notifications()


async def job_weekly_report():
    """주간 리포트 자동 발송."""
    logger.info("Running weekly report job")
    data = await generate_weekly_report()
    blocks = weekly_report_blocks(data)
    await send_dm_blocks(blocks, "📊 주간 리포트")


async def job_calendar_sync():
    """캘린더 동기화."""
    count = await sync_today_events()
    if count:
        logger.info("Calendar sync: %d events", count)


async def job_jira_poll():
    """Jira 댓글 & 멘션 폴링."""
    from app.core.notification import create_jira_notification, process_notification, is_immediate
    from app.slack_bot.views import notification_blocks

    # 댓글 폴링
    comments = await poll_jira_comments()
    for c in comments:
        event_type = "mention" if c.get("is_mention") else "comment"
        notif = create_jira_notification(
            issue_key=c["issue_key"],
            issue_summary=c["issue_summary"],
            event_type=event_type,
            author=c["comment_author"],
            body=c["comment_body"],
            url=c["comment_url"],
            comment_id=c.get("comment_id"),
        )
        notif = await process_notification(notif, config)
        if is_immediate(notif):
            blocks = notification_blocks(notif)
            emoji = "📌" if event_type == "mention" else "💬"
            await send_dm_blocks(blocks, f"{emoji} Jira {event_type}: {c['issue_key']}")

    # 멘션 폴링
    mentions = await poll_jira_mentions()
    for m in mentions:
        notif = create_jira_notification(
            issue_key=m["issue_key"],
            issue_summary=m["issue_summary"],
            event_type="mention",
            url=m["mention_url"],
        )
        notif = await process_notification(notif, config)
        if is_immediate(notif):
            blocks = notification_blocks(notif)
            await send_dm_blocks(blocks, f"📌 Jira 멘션: {m['issue_key']}")

    if comments or mentions:
        logger.info("Jira poll: %d comments, %d mentions", len(comments), len(mentions))


async def job_confluence_poll():
    """Confluence 댓글 & 멘션 폴링."""
    from app.core.notification import create_confluence_notification, process_notification, is_immediate
    from app.slack_bot.views import notification_blocks

    comments = await poll_confluence_comments()
    for c in comments:
        notif = create_confluence_notification(
            page_title=c["page_title"],
            event_type="comment",
            author=c["comment_author"],
            body=c["comment_body"],
            url=c["comment_url"],
        )
        notif = await process_notification(notif, config)
        if is_immediate(notif):
            blocks = notification_blocks(notif)
            await send_dm_blocks(blocks, f"💬 Confluence 댓글: {c['page_title'][:30]}")

    mentions = await poll_confluence_mentions()
    for m in mentions:
        notif = create_confluence_notification(
            page_title=m["page_title"],
            event_type="mention",
            url=m["page_url"],
        )
        notif = await process_notification(notif, config)
        if is_immediate(notif):
            blocks = notification_blocks(notif)
            await send_dm_blocks(blocks, f"📌 Confluence 멘션: {m['page_title'][:30]}")

    if comments or mentions:
        logger.info("Confluence poll: %d comments, %d mentions", len(comments), len(mentions))


async def job_figma_poll():
    """Figma 댓글 & 멘션 폴링."""
    from app.core.notification import create_figma_notification, process_notification, is_immediate
    from app.slack_bot.views import notification_blocks

    comments = await poll_figma_comments(config)
    for c in comments:
        event_type = "mention" if c.get("is_mention") else "comment"
        notif = create_figma_notification(
            file_name=c["file_name"],
            event_type=event_type,
            author=c["comment_author"],
            body=c["comment_body"],
            url=c["comment_url"],
        )
        notif = await process_notification(notif, config)
        if is_immediate(notif):
            blocks = notification_blocks(notif)
            await send_dm_blocks(blocks, f"💬 Figma: {c['comment_author']}")

    if comments:
        logger.info("Figma poll: %d comments", len(comments))


async def job_check_snoozed():
    """스누즈 만료 체크."""
    await check_and_send_snoozed()


# ── FastAPI 앱 ──

fastapi_app = FastAPI(title="work-bot", version="0.1.0")
fastapi_app.include_router(api_router)


# FastAPI startup/shutdown은 main()에서 직접 처리하므로 제거


# ── 메인 실행 ──

async def main():
    """Slack Bot (Socket Mode) + FastAPI를 동시 실행합니다."""
    # DB 초기화
    await init_db()
    logger.info("Database initialized")

    # Slack Bot 생성
    slack_app = create_slack_app(config)

    # 스케줄러 설정
    setup_scheduler(config, {
        "daily_briefing": job_daily_briefing,
        "batch_flush": job_batch_flush,
        "weekly_report": job_weekly_report,
        "jira_poll": job_jira_poll,
        "confluence_poll": job_confluence_poll,
        "figma_poll": job_figma_poll,
        "calendar_sync": job_calendar_sync,
        "check_snoozed": job_check_snoozed,
    })
    scheduler.start()
    logger.info("Scheduler started")

    # Socket Mode로 Slack Bot 실행
    app_token = os.getenv("SLACK_APP_TOKEN")
    if not app_token:
        logger.error("SLACK_APP_TOKEN is required for Socket Mode")
        return

    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    socket_handler = AsyncSocketModeHandler(slack_app, app_token)

    # FastAPI + Slack Bot 동시 실행
    uvicorn_config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)

    logger.info("Starting work-bot...")
    logger.info("  Slack Bot: Socket Mode")
    logger.info("  FastAPI: http://0.0.0.0:8000")
    logger.info("  Scheduler: Active")

    try:
        await asyncio.gather(
            socket_handler.start_async(),
            server.serve(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        scheduler.shutdown(wait=False)
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
