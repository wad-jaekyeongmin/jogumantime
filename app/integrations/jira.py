"""Jira 연동 — 댓글 & 멘션 알림 폴링."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

# 마지막 폴링 시각 (메모리에 유지, 재시작 시 최근 10분부터)
_last_poll: datetime | None = None


def _auth() -> tuple[str, HTTPBasicAuth, dict]:
    """Atlassian 인증 정보 반환: (domain, auth, headers)."""
    domain = os.getenv("ATLASSIAN_DOMAIN", "")
    email = os.getenv("ATLASSIAN_EMAIL", "")
    token = os.getenv("ATLASSIAN_API_TOKEN", "")
    auth = HTTPBasicAuth(email, token)
    headers = {"Accept": "application/json"}
    return domain, auth, headers


def _jql_datetime(dt: datetime) -> str:
    """Jira JQL용 datetime 문자열 (yyyy-MM-dd HH:mm)."""
    return dt.strftime("%Y-%m-%d %H:%M")


async def get_my_account_id() -> str | None:
    """현재 인증된 사용자의 Atlassian account ID 조회."""
    domain, auth, headers = _auth()
    try:
        resp = requests.get(
            f"{domain}/rest/api/3/myself",
            auth=auth,
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("accountId")
    except Exception:
        logger.exception("Failed to get Jira account ID")
    return None


async def poll_jira_comments() -> list[dict]:
    """
    내 활성 이슈에 달린 새 댓글을 폴링.
    반환: [{"issue_key", "issue_summary", "comment_author", "comment_body", "comment_url"}, ...]
    """
    global _last_poll

    domain, auth, headers = _auth()
    if not domain:
        return []

    now = datetime.now()
    since = _last_poll or (now - timedelta(minutes=10))
    _last_poll = now

    results: list[dict] = []

    try:
        # 1) 내게 할당된 DONE 아닌 이슈 조회
        jql = (
            "assignee = currentUser() "
            "AND status != DONE "
            f"AND updated >= '{_jql_datetime(since)}' "
            "ORDER BY updated DESC"
        )
        resp = requests.get(
            f"{domain}/rest/api/3/search/jql",
            auth=auth,
            headers=headers,
            params={"jql": jql, "maxResults": 30, "fields": "summary"},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("Jira search failed: %s", resp.status_code)
            return []

        issues = resp.json().get("issues", [])

        # 2) 각 이슈의 댓글 확인
        for issue in issues:
            issue_key = issue["key"]
            issue_summary = issue["fields"]["summary"]
            comments = await _get_recent_comments(
                domain, auth, headers, issue_key, since
            )
            for c in comments:
                results.append({
                    "issue_key": issue_key,
                    "issue_summary": issue_summary,
                    "comment_author": c["author"],
                    "comment_body": c["body"],
                    "comment_id": c["comment_id"],
                    "comment_url": f"{domain}/browse/{issue_key}",
                    "is_mention": c.get("is_mention", False),
                })

    except Exception:
        logger.exception("Jira comment polling failed")

    return results


async def poll_jira_mentions() -> list[dict]:
    """
    내가 멘션된 이슈를 폴링 (JQL로 텍스트 검색).
    반환: [{"issue_key", "issue_summary", "mention_url"}, ...]
    """
    global _last_poll

    domain, auth, headers = _auth()
    if not domain:
        return []

    now = datetime.now()
    since = _last_poll or (now - timedelta(minutes=10))

    results: list[dict] = []

    try:
        account_id = await get_my_account_id()
        if not account_id:
            return []

        # 내가 멘션된 최근 이슈 (watcher or mentioned)
        jql = (
            f"issueFunction in commented("
            f"'by not currentUser() after \"{_jql_datetime(since)}\"') "
            f"AND text ~ '[~accountid:{account_id}]' "
            "ORDER BY updated DESC"
        )

        # issueFunction은 ScriptRunner 필요 → 대신 심플하게
        # 최근 업데이트된 이슈 중 내가 멘션된 댓글 찾기
        jql_simple = (
            f"status != DONE "
            f"AND updated >= '{_jql_datetime(since)}' "
            f"AND text ~ '[~accountid:{account_id}]' "
            "ORDER BY updated DESC"
        )

        resp = requests.get(
            f"{domain}/rest/api/3/search/jql",
            auth=auth,
            headers=headers,
            params={"jql": jql_simple, "maxResults": 20, "fields": "summary"},
            timeout=15,
        )
        if resp.status_code == 200:
            for issue in resp.json().get("issues", []):
                results.append({
                    "issue_key": issue["key"],
                    "issue_summary": issue["fields"]["summary"],
                    "mention_url": f"{domain}/browse/{issue['key']}",
                })

    except Exception:
        logger.exception("Jira mention polling failed")

    return results


async def _get_recent_comments(
    domain: str,
    auth: HTTPBasicAuth,
    headers: dict,
    issue_key: str,
    since: datetime,
) -> list[dict]:
    """이슈의 최근 댓글 중 since 이후에 작성된 것만 반환."""
    try:
        resp = requests.get(
            f"{domain}/rest/api/3/issue/{issue_key}/comment",
            auth=auth,
            headers=headers,
            params={"orderBy": "-created", "maxResults": 10},
            timeout=10,
        )
        if resp.status_code != 200:
            return []

        comments = resp.json().get("comments", [])
        recent: list[dict] = []

        # 본인이 쓴 댓글은 제외
        my_email = os.getenv("ATLASSIAN_EMAIL", "")

        for c in comments:
            created = c.get("created", "")
            # Jira datetime: "2026-04-17T10:30:00.000+0900"
            try:
                created_dt = datetime.fromisoformat(created)
                created_naive = created_dt.replace(tzinfo=None)
            except (ValueError, TypeError):
                continue

            if created_naive <= since:
                continue

            author_email = c.get("author", {}).get("emailAddress", "")
            author_name = c.get("author", {}).get("displayName", "unknown")

            # 본인 댓글 스킵 (테스트용 임시 해제)
            # if author_email == my_email:
            #     continue

            # ADF body → plain text 변환
            body_raw = c.get("body", {})
            body = _adf_to_text(body_raw)

            # 댓글 내 멘션 감지 (ADF에서 내 accountId 검색)
            import json
            body_json = json.dumps(body_raw)
            my_account_id = await get_my_account_id()
            is_mention = my_account_id and my_account_id in body_json

            recent.append({
                "author": author_name,
                "body": body[:500],
                "comment_id": c.get("id", ""),
                "is_mention": is_mention,
            })

        return recent

    except Exception:
        logger.exception("Failed to get comments for %s", issue_key)
        return []


def _adf_to_text(adf: dict) -> str:
    """Atlassian Document Format → plain text (간단 변환)."""
    if not adf or not isinstance(adf, dict):
        return ""

    texts: list[str] = []

    def _walk(node: dict | list):
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if isinstance(node, dict):
            if node.get("type") == "text":
                texts.append(node.get("text", ""))
            elif node.get("type") == "mention":
                texts.append(f"@{node.get('attrs', {}).get('text', '')}")
            for child in node.get("content", []):
                _walk(child)

    _walk(adf)
    return " ".join(texts).strip()
