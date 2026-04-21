"""Google Calendar 연동 (읽기/쓰기)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.db.models import CalendarEvent
from app.db.queries import upsert_calendar_event

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = "token.json"


def _get_client_config() -> dict:
    """환경변수에서 OAuth 클라이언트 설정을 생성합니다."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def get_calendar_service():
    """Google Calendar API 서비스 객체를 반환합니다."""
    creds = None
    if Path(TOKEN_PATH).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_config = _get_client_config()
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=8000)
        Path(TOKEN_PATH).write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


async def sync_today_events():
    """오늘의 Google Calendar 이벤트를 동기화합니다."""
    try:
        service = get_calendar_service()
        calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")

        now = datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_of_day.isoformat() + "Z",
            timeMax=end_of_day.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])
        logger.info("Synced %d calendar events for today", len(events))

        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            end = event["end"].get("dateTime", event["end"].get("date", ""))
            is_all_day = "date" in event["start"]

            attendees = None
            if event.get("attendees"):
                attendees = json.dumps([a.get("email", "") for a in event["attendees"]])

            cal_event = CalendarEvent(
                event_id=event["id"],
                title=event.get("summary", "(제목 없음)"),
                description=event.get("description"),
                start_time=start,
                end_time=end,
                location=event.get("location"),
                attendees=attendees,
                is_all_day=is_all_day,
            )
            await upsert_calendar_event(cal_event)

        return len(events)

    except Exception:
        logger.exception("Failed to sync calendar events")
        return 0


async def sync_week_events():
    """이번 주의 Google Calendar 이벤트를 동기화합니다."""
    try:
        service = get_calendar_service()
        calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")

        now = datetime.now()
        monday = now - timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        sunday = monday + timedelta(days=7)

        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=monday.isoformat() + "Z",
            timeMax=sunday.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            end = event["end"].get("dateTime", event["end"].get("date", ""))
            is_all_day = "date" in event["start"]

            attendees = None
            if event.get("attendees"):
                attendees = json.dumps([a.get("email", "") for a in event["attendees"]])

            cal_event = CalendarEvent(
                event_id=event["id"],
                title=event.get("summary", "(제목 없음)"),
                description=event.get("description"),
                start_time=start,
                end_time=end,
                location=event.get("location"),
                attendees=attendees,
                is_all_day=is_all_day,
            )
            await upsert_calendar_event(cal_event)

        return len(events)

    except Exception:
        logger.exception("Failed to sync week events")
        return 0


async def create_calendar_event(
    title: str,
    start_time: str,
    end_time: str,
    description: str | None = None,
) -> str | None:
    """Google Calendar에 새 이벤트를 생성합니다.

    Returns:
        생성된 이벤트의 HTML 링크 또는 None.
    """
    try:
        service = get_calendar_service()
        calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")

        event_body = {
            "summary": title,
            "start": {"dateTime": start_time, "timeZone": "Asia/Seoul"},
            "end": {"dateTime": end_time, "timeZone": "Asia/Seoul"},
        }
        if description:
            event_body["description"] = description

        event = service.events().insert(
            calendarId=calendar_id,
            body=event_body,
        ).execute()

        logger.info("Created calendar event: %s", event.get("htmlLink"))

        # DB에도 저장
        cal_event = CalendarEvent(
            event_id=event["id"],
            title=title,
            start_time=start_time,
            end_time=end_time,
            description=description,
        )
        await upsert_calendar_event(cal_event)

        return event.get("htmlLink")

    except Exception:
        logger.exception("Failed to create calendar event")
        return None
