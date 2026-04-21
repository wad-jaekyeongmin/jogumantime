"""Claude API를 통한 우선순위 분석."""
from __future__ import annotations

import json
import logging
import os

import anthropic

from app.db.models import Notification

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
    return _client


SYSTEM_PROMPT = """당신은 PM의 업무 알림 우선순위를 분석하는 AI 비서입니다.
주어진 알림 메시지를 분석하여 우선순위를 판단하세요.

응답은 반드시 JSON 형식으로:
{
  "suggested_level": "URGENT|HIGH|MEDIUM|LOW",
  "analysis": "한 줄 분석 이유",
  "action_needed": true|false
}

판단 기준:
- URGENT: 즉시 대응 필요 (장애, 배포 실패, 긴급 요청)
- HIGH: 오늘 내 대응 필요 (중요 리뷰 요청, 일정 변경)
- MEDIUM: 확인은 필요하나 급하지 않음 (일반 리뷰, FYI)
- LOW: 나중에 봐도 됨 (잡담, 공지 등)"""


async def analyze_priority(notification: Notification) -> dict | None:
    """Claude Sonnet으로 알림의 우선순위를 분석합니다."""
    try:
        client = get_client()

        user_msg = f"""출처: {notification.source}
채널: {notification.channel_name or 'N/A'}
보낸이: {notification.sender_name or 'N/A'}
내용: {notification.content[:500]}"""

        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        text = response.content[0].text.strip()
        # JSON 파싱
        if text.startswith("{"):
            return json.loads(text)
        # 코드블록 안에 JSON이 있는 경우
        if "```" in text:
            json_str = text.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
            return json.loads(json_str.strip())
        return None

    except Exception:
        logger.exception("Claude AI analysis failed")
        return None
