"""APScheduler 설정 및 예약 작업."""
from __future__ import annotations

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def setup_scheduler(config: dict, jobs: dict):
    """
    config.yaml의 schedule 섹션을 기반으로 스케줄러를 설정합니다.

    jobs: {
        "daily_briefing": async callable,
        "batch_flush": async callable,
        "weekly_report": async callable,
        "calendar_sync": async callable,
        "check_snoozed": async callable,
    }
    """
    tz = config.get("schedule", {}).get("timezone", "Asia/Seoul")
    sched = config.get("schedule", {})

    # 일일 브리핑
    briefing_conf = sched.get("daily_briefing", {})
    if briefing_conf.get("enabled") and "daily_briefing" in jobs:
        hour, minute = briefing_conf["time"].split(":")
        day_map = {"mon": "0", "tue": "1", "wed": "2", "thu": "3", "fri": "4", "sat": "5", "sun": "6"}
        days = ",".join(day_map.get(d, d) for d in briefing_conf.get("days", []))
        scheduler.add_job(
            jobs["daily_briefing"],
            CronTrigger(hour=int(hour), minute=int(minute), day_of_week=days, timezone=tz),
            id="daily_briefing",
            name="일일 브리핑",
        )
        logger.info("Scheduled daily briefing at %s", briefing_conf["time"])

    # 배치 알림 플러시
    batch_conf = sched.get("batch_flush", {})
    if batch_conf.get("enabled") and "batch_flush" in jobs:
        interval = batch_conf.get("interval_minutes", 30)
        start_h = batch_conf.get("start_hour", 9)
        end_h = batch_conf.get("end_hour", 19)
        day_map = {"mon": "0", "tue": "1", "wed": "2", "thu": "3", "fri": "4", "sat": "5", "sun": "6"}
        days = ",".join(day_map.get(d, d) for d in batch_conf.get("days", []))
        scheduler.add_job(
            jobs["batch_flush"],
            CronTrigger(
                minute=f"*/{interval}",
                hour=f"{start_h}-{end_h}",
                day_of_week=days,
                timezone=tz,
            ),
            id="batch_flush",
            name="배치 알림 플러시",
        )
        logger.info("Scheduled batch flush every %d min (%d:00~%d:00)", interval, start_h, end_h)

    # 주간 리포트
    report_conf = sched.get("weekly_report", {})
    if report_conf.get("enabled") and "weekly_report" in jobs:
        hour, minute = report_conf["time"].split(":")
        day_map = {"mon": "0", "tue": "1", "wed": "2", "thu": "3", "fri": "4"}
        day = day_map.get(report_conf.get("day", "fri"), "4")
        scheduler.add_job(
            jobs["weekly_report"],
            CronTrigger(hour=int(hour), minute=int(minute), day_of_week=day, timezone=tz),
            id="weekly_report",
            name="주간 리포트",
        )
        logger.info("Scheduled weekly report on %s at %s", report_conf.get("day"), report_conf["time"])

    # Jira 폴링
    jira_conf = sched.get("jira_poll", {})
    if jira_conf.get("enabled") and "jira_poll" in jobs:
        interval = jira_conf.get("interval_minutes", 3)
        scheduler.add_job(
            jobs["jira_poll"],
            IntervalTrigger(minutes=interval),
            id="jira_poll",
            name="Jira 폴링",
        )
        logger.info("Scheduled Jira poll every %d min", interval)

    # Figma 폴링
    figma_conf = sched.get("figma_poll", {})
    if figma_conf.get("enabled") and "figma_poll" in jobs:
        interval = figma_conf.get("interval_minutes", 3)
        scheduler.add_job(
            jobs["figma_poll"],
            IntervalTrigger(minutes=interval),
            id="figma_poll",
            name="Figma 폴링",
        )
        logger.info("Scheduled Figma poll every %d min", interval)

    # Confluence 폴링
    conf_conf = sched.get("confluence_poll", {})
    if conf_conf.get("enabled") and "confluence_poll" in jobs:
        interval = conf_conf.get("interval_minutes", 3)
        scheduler.add_job(
            jobs["confluence_poll"],
            IntervalTrigger(minutes=interval),
            id="confluence_poll",
            name="Confluence 폴링",
        )
        logger.info("Scheduled Confluence poll every %d min", interval)

    # 캘린더 동기화
    cal_conf = sched.get("calendar_sync", {})
    if cal_conf.get("enabled") and "calendar_sync" in jobs:
        interval = cal_conf.get("interval_minutes", 5)
        scheduler.add_job(
            jobs["calendar_sync"],
            IntervalTrigger(minutes=interval),
            id="calendar_sync",
            name="캘린더 동기화",
        )
        logger.info("Scheduled calendar sync every %d min", interval)

    # 스누즈 체크 (매분)
    if "check_snoozed" in jobs:
        scheduler.add_job(
            jobs["check_snoozed"],
            IntervalTrigger(minutes=1),
            id="check_snoozed",
            name="스누즈 체크",
        )

    return scheduler
