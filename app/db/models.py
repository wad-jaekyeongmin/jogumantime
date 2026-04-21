from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PriorityLevel(str, Enum):
    URGENT = "URGENT"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    NOTIFIED = "notified"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"


@dataclass
class Notification:
    source: str
    content: str
    source_id: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    sender_name: str | None = None
    url: str | None = None
    priority_score: int = 0
    priority_level: PriorityLevel = PriorityLevel.LOW
    ai_analysis: str | None = None
    status: NotificationStatus = NotificationStatus.PENDING
    snoozed_until: datetime | None = None
    batch_group: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    notified_at: datetime | None = None
    dismissed_at: datetime | None = None
    id: int | None = None

    @classmethod
    def from_row(cls, row) -> Notification:
        return cls(
            id=row["id"],
            source=row["source"],
            source_id=row["source_id"],
            channel_id=row["channel_id"],
            channel_name=row["channel_name"],
            sender_name=row["sender_name"],
            content=row["content"],
            url=row["url"],
            priority_score=row["priority_score"],
            priority_level=PriorityLevel(row["priority_level"]),
            ai_analysis=row["ai_analysis"],
            status=NotificationStatus(row["status"]),
            snoozed_until=row["snoozed_until"],
            batch_group=row["batch_group"],
            created_at=row["created_at"],
            notified_at=row["notified_at"],
            dismissed_at=row["dismissed_at"],
        )


@dataclass
class CalendarEvent:
    event_id: str
    title: str
    start_time: str
    end_time: str
    description: str | None = None
    location: str | None = None
    attendees: str | None = None
    is_all_day: bool = False
    synced_at: datetime = field(default_factory=datetime.now)
    id: int | None = None

    @classmethod
    def from_row(cls, row) -> CalendarEvent:
        return cls(
            id=row["id"],
            event_id=row["event_id"],
            title=row["title"],
            description=row["description"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            location=row["location"],
            attendees=row["attendees"],
            is_all_day=bool(row["is_all_day"]),
            synced_at=row["synced_at"],
        )
