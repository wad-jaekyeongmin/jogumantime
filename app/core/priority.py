"""우선순위 스코어링 (규칙 기반 + Claude AI 분석)."""
from __future__ import annotations

import logging

import os

from app.db.models import Notification, PriorityLevel

logger = logging.getLogger(__name__)


def rule_based_score(notification: Notification, config: dict) -> int:
    """config.yaml 기반 규칙 스코어링."""
    priority_config = config.get("priority", {})
    score = 0

    # 1. 채널 가중치
    channel_weights = priority_config.get("channel_weights", {})
    channel = notification.channel_name or ""
    for pattern, weight in channel_weights.items():
        if pattern in channel:
            score += weight
            break

    # 2. 키워드 부스트
    keyword_boosts = priority_config.get("keyword_boosts", {})
    content_lower = notification.content.lower()
    for keyword, boost in keyword_boosts.items():
        if keyword.lower() in content_lower:
            score += boost

    # 3. 멘션/DM 부스트
    if notification.source == "slack":
        # DM은 기본 높은 점수
        if notification.channel_name and notification.channel_name.startswith("D"):
            score += 8
        # @멘션은 즉시 DM (HIGH 보장)
        if "<@" in notification.content:
            score += 15

    # 4. 캘린더 알림은 기본 MEDIUM
    if notification.source == "calendar":
        score += 12

    # 5. Jira 알림
    if notification.source == "jira":
        score += 12  # 기본 MEDIUM
        if "멘션" in notification.content:
            score += 10  # 멘션은 즉시 DM

    # 6. Confluence 알림
    if notification.source == "confluence":
        score += 12  # 기본 MEDIUM
        if "멘션" in notification.content:
            score += 10  # 멘션은 즉시 DM

    # 7. Figma 알림
    if notification.source == "figma":
        score += 12  # 기본 MEDIUM
        if "멘션" in notification.content:
            score += 10  # 멘션은 즉시 DM

    return score


def score_to_level(score: int, config: dict) -> PriorityLevel:
    thresholds = config.get("priority", {}).get("thresholds", {})
    if score >= thresholds.get("urgent", 25):
        return PriorityLevel.URGENT
    if score >= thresholds.get("high", 18):
        return PriorityLevel.HIGH
    if score >= thresholds.get("medium", 10):
        return PriorityLevel.MEDIUM
    return PriorityLevel.LOW


async def score_notification(
    notification: Notification, config: dict,
) -> Notification:
    """1단계: 규칙 기반 스코어링, 2단계: AI 분석(MEDIUM 이상)."""
    score = rule_based_score(notification, config)
    notification.priority_score = score
    notification.priority_level = score_to_level(score, config)

    # 2단계: AI 분석 (MEDIUM 이상만, 비용 절감)
    ai_min = config.get("priority", {}).get("ai_analysis_min_score", 10)
    if score >= ai_min and os.getenv("ANTHROPIC_API_KEY"):
        try:
            from app.integrations.claude_ai import analyze_priority

            ai_result = await analyze_priority(notification)
            if ai_result:
                notification.ai_analysis = ai_result.get("analysis", "")
                ai_level = ai_result.get("suggested_level")
                if ai_level and ai_level in PriorityLevel.__members__:
                    ai_priority = PriorityLevel(ai_level)
                    # AI가 더 높은 우선순위를 제안하면 승격
                    levels = [PriorityLevel.LOW, PriorityLevel.MEDIUM, PriorityLevel.HIGH, PriorityLevel.URGENT]
                    if levels.index(ai_priority) > levels.index(notification.priority_level):
                        notification.priority_level = ai_priority
                        logger.info("AI upgraded priority to %s", ai_priority.value)
        except Exception:
            logger.exception("AI priority analysis failed, using rule-based score")

    return notification
