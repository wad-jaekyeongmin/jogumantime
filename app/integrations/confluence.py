"""Confluence 연동 — 댓글 & 멘션 알림 폴링."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

_last_poll: datetime | None = None
_my_account_id: str | None = None
_my_page_ids: set[str] = set()
_my_pages_refreshed_at: datetime | None = None


def _auth() -> tuple[str, HTTPBasicAuth, dict]:
    domain = os.getenv("ATLASSIAN_DOMAIN", "")
    email = os.getenv("ATLASSIAN_EMAIL", "")
    token = os.getenv("ATLASSIAN_API_TOKEN", "")
    return domain, HTTPBasicAuth(email, token), {"Accept": "application/json"}


def _get_my_account_id(domain: str, auth: HTTPBasicAuth, headers: dict) -> str:
    global _my_account_id
    if _my_account_id:
        return _my_account_id
    try:
        resp = requests.get(
            f"{domain}/rest/api/3/myself",
            auth=auth, headers=headers, timeout=10,
        )
        if resp.status_code == 200:
            _my_account_id = resp.json().get("accountId", "")
            return _my_account_id
    except Exception:
        logger.exception("Failed to get account ID")
    return ""


def _refresh_my_pages(domain: str, auth: HTTPBasicAuth, headers: dict) -> None:
    """내가 기여(contributor)했거나 만든(creator) 페이지 ID 목록을 갱신 (30분마다)."""
    global _my_page_ids, _my_pages_refreshed_at

    now = datetime.now(timezone.utc)
    if _my_pages_refreshed_at and (now - _my_pages_refreshed_at) < timedelta(minutes=30):
        return

    try:
        cql = (
            "type = page AND "
            "(contributor = currentUser() OR creator = currentUser()) "
            "ORDER BY lastModified DESC"
        )
        start = 0
        page_ids: set[str] = set()

        while True:
            resp = requests.get(
                f"{domain}/wiki/rest/api/content/search",
                auth=auth, headers=headers,
                params={"cql": cql, "limit": 50, "start": start},
                timeout=15,
            )
            if resp.status_code != 200:
                break

            results = resp.json().get("results", [])
            if not results:
                break

            for p in results:
                page_ids.add(p["id"])

            start += len(results)
            if start >= 500:
                break

        _my_page_ids = page_ids
        _my_pages_refreshed_at = now
        logger.info("Refreshed my Confluence pages: %d pages", len(page_ids))

    except Exception:
        logger.exception("Failed to refresh my Confluence pages")


async def poll_confluence_comments(config: dict | None = None) -> list[dict]:
    """
    내가 관여한 페이지 중 최근 업데이트된 것들의 댓글을 직접 조회.
    반환: [{"page_title", "comment_author", "comment_body", "comment_url", "is_mention"}, ...]
    """
    global _last_poll

    domain, auth, headers = _auth()
    if not domain:
        return []

    exclude_ids = set()
    if config:
        raw = config.get("schedule", {}).get("confluence_poll", {}).get("exclude_page_ids", [])
        exclude_ids = {str(pid) for pid in raw}

    now = datetime.now(timezone.utc)
    since = _last_poll or (now - timedelta(minutes=10))
    _last_poll = now

    my_id = _get_my_account_id(domain, auth, headers)
    _refresh_my_pages(domain, auth, headers)

    results: list[dict] = []

    try:
        # 내 페이지 중 최근 업데이트된 것들 찾기
        since_str = since.strftime("%Y-%m-%d %H:%M")
        cql = (
            f"type = page AND "
            f"(contributor = currentUser() OR creator = currentUser()) AND "
            f"lastModified >= '{since_str}' "
            f"ORDER BY lastModified DESC"
        )
        resp = requests.get(
            f"{domain}/wiki/rest/api/content/search",
            auth=auth, headers=headers,
            params={"cql": cql, "limit": 20},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("Confluence page search failed: %s", resp.status_code)
            return []

        pages = resp.json().get("results", [])

        for page in pages:
            page_id = page["id"]
            page_title = page.get("title", "?")
            page_url = f"{domain}/wiki{page.get('_links', {}).get('webui', '')}"

            if page_id in exclude_ids:
                continue

            # 이 페이지의 최근 댓글 확인 (footer + inline)
            new_comments = _get_recent_page_comments(
                domain, auth, headers, page_id, since, my_id,
            )
            for c in new_comments:
                results.append({
                    "page_title": page_title,
                    "comment_author": c["author"],
                    "comment_body": c["body"],
                    "comment_url": page_url,
                    "is_mention": c["is_mention"],
                })

        # 추가: CQL 댓글 검색으로 내 페이지 외에서도 멘션된 댓글 잡기
        cql_comments = f"type = comment AND created >= '{since_str}'"
        resp2 = requests.get(
            f"{domain}/wiki/rest/api/content/search",
            auth=auth, headers=headers,
            params={
                "cql": cql_comments,
                "limit": 30,
                "expand": "ancestors,version,body.atlas_doc_format",
            },
            timeout=15,
        )
        if resp2.status_code == 200:
            for c in resp2.json().get("results", []):
                author_id = c.get("version", {}).get("by", {}).get("accountId", "")
                if author_id == my_id:
                    continue

                body_raw = c.get("body", {}).get("atlas_doc_format", {}).get("value", "")
                if my_id not in body_raw:
                    continue

                ancestors = c.get("ancestors", [])
                if not ancestors:
                    continue

                author_name = c.get("version", {}).get("by", {}).get("displayName", "?")
                page_title = ancestors[-1]["title"]
                page_url = f"{domain}/wiki{ancestors[-1].get('_links', {}).get('webui', '')}"
                body_text = _adf_to_text(body_raw)

                results.append({
                    "page_title": page_title,
                    "comment_author": author_name,
                    "comment_body": body_text[:500],
                    "comment_url": page_url,
                    "is_mention": True,
                })

    except Exception:
        logger.exception("Confluence comment polling failed")

    return results


async def poll_confluence_mentions() -> list[dict]:
    """
    내가 멘션된 Confluence 페이지 본문 폴링.
    반환: [{"page_title", "page_url"}, ...]
    """
    domain, auth, headers = _auth()
    if not domain:
        return []

    my_id = _get_my_account_id(domain, auth, headers)
    if not my_id:
        return []

    now = datetime.now(timezone.utc)
    since = _last_poll or (now - timedelta(minutes=10))
    since_str = since.strftime("%Y-%m-%d %H:%M")

    results: list[dict] = []

    try:
        cql = (
            f"type = page AND "
            f"lastModified >= '{since_str}' AND "
            f"text ~ '{my_id}'"
        )
        resp = requests.get(
            f"{domain}/wiki/rest/api/content/search",
            auth=auth, headers=headers,
            params={"cql": cql, "limit": 20},
            timeout=15,
        )
        if resp.status_code == 200:
            for page in resp.json().get("results", []):
                page_url = f"{domain}/wiki{page.get('_links', {}).get('webui', '')}"
                results.append({
                    "page_title": page.get("title", ""),
                    "page_url": page_url,
                })

    except Exception:
        logger.exception("Confluence mention polling failed")

    return results


def _get_recent_page_comments(
    domain: str,
    auth: HTTPBasicAuth,
    headers: dict,
    page_id: str,
    since: datetime,
    my_id: str,
) -> list[dict]:
    """페이지의 모든 댓글(footer + inline) 중 since 이후, 본인 제외."""
    results: list[dict] = []

    for comment_type in ("comment", "inline-comment"):
        try:
            # v1 API: child/comment (footer 댓글)
            if comment_type == "comment":
                url = f"{domain}/wiki/rest/api/content/{page_id}/child/comment"
            else:
                # v2 API: inline comments
                url = f"{domain}/wiki/api/v2/pages/{page_id}/inline-comments"

            resp = requests.get(
                url, auth=auth, headers=headers,
                params={"limit": 10, "expand": "version,body.atlas_doc_format"}
                if comment_type == "comment"
                else {"limit": 10, "body-format": "atlas_doc_format"},
                timeout=10,
            )
            if resp.status_code != 200:
                continue

            comments = resp.json().get("results", [])

            for c in comments:
                # 시간 파싱
                if comment_type == "comment":
                    when_str = c.get("version", {}).get("when", "")
                    author_id = c.get("version", {}).get("by", {}).get("accountId", "")
                    author_name = c.get("version", {}).get("by", {}).get("displayName", "?")
                    body_raw = c.get("body", {}).get("atlas_doc_format", {}).get("value", "")
                else:
                    when_str = c.get("createdAt", "")
                    author_id = c.get("authorId", "")
                    author_name = author_id  # v2 API에서는 이름 별도 조회 필요
                    body_data = c.get("body", {})
                    if isinstance(body_data, dict) and "atlas_doc_format" in body_data:
                        body_raw = body_data["atlas_doc_format"].get("value", "")
                    else:
                        body_raw = ""

                if not when_str:
                    continue

                try:
                    created_dt = datetime.fromisoformat(
                        when_str.replace("Z", "+00:00")
                    )
                    since_aware = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    if created_dt <= since_aware:
                        continue
                except (ValueError, TypeError):
                    continue

                # 본인 댓글 스킵
                if author_id == my_id:
                    continue

                body_text = _adf_to_text(body_raw)
                is_mention = my_id in body_raw

                results.append({
                    "author": author_name,
                    "body": body_text[:500],
                    "is_mention": is_mention,
                })

        except Exception:
            logger.exception("Failed to get %s for page %s", comment_type, page_id)

    return results


def _adf_to_text(adf_str: str) -> str:
    """ADF JSON 문자열 → plain text."""
    if not adf_str:
        return ""
    try:
        adf = json.loads(adf_str) if isinstance(adf_str, str) else adf_str
    except (json.JSONDecodeError, TypeError):
        return str(adf_str)

    texts: list[str] = []

    def _walk(node):
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
