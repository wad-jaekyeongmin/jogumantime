"""Figma 연동 — 댓글 & 멘션 알림 폴링."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

_last_poll: datetime | None = None
_my_page_node_ids: set[str] = set()
_my_pages_refreshed_at: datetime | None = None
_my_user_id: str | None = None
_my_handle: str | None = None


def _headers() -> dict:
    return {"X-Figma-Token": os.getenv("FIGMA_API_TOKEN", "")}


def _get_my_info() -> tuple[str, str]:
    """내 Figma user ID와 handle 반환."""
    global _my_user_id, _my_handle
    if _my_user_id and _my_handle:
        return _my_user_id, _my_handle
    try:
        resp = requests.get(
            "https://api.figma.com/v1/me",
            headers=_headers(), timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            _my_user_id = str(data.get("id", ""))
            _my_handle = data.get("handle", "")
            return _my_user_id, _my_handle
    except Exception:
        logger.exception("Failed to get Figma user info")
    return "", ""


def _refresh_my_pages(file_keys: list[str], name_keyword: str) -> None:
    """파일의 페이지 중 name_keyword가 포함된 페이지의 자식 node ID 범위를 캐싱 (30분마다)."""
    global _my_page_node_ids, _my_pages_refreshed_at

    now = datetime.now(timezone.utc)
    if _my_pages_refreshed_at and (now - _my_pages_refreshed_at) < timedelta(minutes=30):
        return

    headers = _headers()
    page_ids: set[str] = set()

    for file_key in file_keys:
        try:
            resp = requests.get(
                f"https://api.figma.com/v1/files/{file_key}?depth=1",
                headers=headers, timeout=15,
            )
            if resp.status_code != 200:
                continue

            doc = resp.json().get("document", {})
            for child in doc.get("children", []):
                if name_keyword in child.get("name", ""):
                    page_ids.add(child["id"])

        except Exception:
            logger.exception("Failed to get Figma file %s pages", file_key)

    _my_page_node_ids = page_ids
    _my_pages_refreshed_at = now
    logger.info("Refreshed my Figma pages: %d pages with '%s'", len(page_ids), name_keyword)


def _is_on_my_page(comment: dict, file_key: str) -> bool:
    """댓글이 내 페이지에 달린 것인지 확인."""
    client_meta = comment.get("client_meta")
    if not client_meta:
        return False

    node_id = client_meta.get("node_id", "")
    if not node_id:
        return False

    # node_id의 상위 페이지를 알아야 함
    # Figma node ID는 "pageId:nodeId" 패턴이 아니라 독립적
    # → 파일 구조에서 node가 어느 페이지에 속하는지 확인 필요
    # 간단한 방법: node_id의 prefix가 페이지 ID와 같은지 체크
    # (Figma에서 같은 페이지의 노드는 보통 같은 prefix를 공유)

    # 더 정확한 방법: 파일을 depth=2로 가져와서 매핑
    # → API 호출 줄이기 위해 order_id 기반으로 근사

    # 실용적 방법: 댓글의 node_id로 GET /v1/files/:key/nodes?ids=nodeId
    # → 응답에서 해당 노드의 부모 페이지 확인
    return False  # _check_node_page에서 처리


async def poll_figma_comments(config: dict | None = None) -> list[dict]:
    """
    감시 중인 Figma 파일의 새 댓글 폴링.
    조건: 내 페이지(이름에 keyword 포함)에 달린 댓글 OR 나를 멘션한 댓글.
    반환: [{"file_name", "comment_author", "comment_body", "comment_url", "is_mention"}, ...]
    """
    global _last_poll

    figma_conf = {}
    if config:
        figma_conf = config.get("schedule", {}).get("figma_poll", {})

    # DB에서 감시 중인 파일 목록 가져오기 (config fallback)
    from app.db.queries import get_figma_watched_files
    db_files = await get_figma_watched_files()
    config_files = figma_conf.get("file_keys", [])
    file_keys = list(set(db_files + config_files))
    name_keyword = figma_conf.get("page_name_keyword", "경민")

    if not file_keys:
        return []

    headers = _headers()
    if not headers.get("X-Figma-Token"):
        return []

    now = datetime.now(timezone.utc)
    since = _last_poll or (now - timedelta(minutes=10))
    _last_poll = now

    my_id, my_handle = _get_my_info()
    _refresh_my_pages(file_keys, name_keyword)

    results: list[dict] = []

    for file_key in file_keys:
        try:
            resp = requests.get(
                f"https://api.figma.com/v1/files/{file_key}/comments",
                headers=headers, timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("Figma comments failed for %s: %s", file_key, resp.status_code)
                continue

            file_name = _get_file_name(file_key, headers)
            comments = resp.json().get("comments", [])

            for c in comments:
                # 시간 필터
                created = c.get("created_at", "")
                try:
                    created_dt = datetime.fromisoformat(
                        created.replace("Z", "+00:00")
                    )
                    since_aware = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
                    if created_dt <= since_aware:
                        continue
                except (ValueError, TypeError):
                    continue

                # 이미 해결된 댓글 스킵
                if c.get("resolved_at"):
                    continue

                # 본인 댓글 스킵
                author_id = str(c.get("user", {}).get("id", ""))
                if author_id == my_id:
                    continue

                author_name = c.get("user", {}).get("handle", "?")
                message = c.get("message", "")
                comment_id = c.get("id", "")

                # 멘션 확인 (핸들로 검색)
                is_mention = my_handle and my_handle in message

                # 내 페이지에 달린 댓글인지 확인
                is_on_my_page = _check_comment_on_my_page(c)

                if not is_mention and not is_on_my_page:
                    continue

                comment_url = f"https://www.figma.com/design/{file_key}?comment={comment_id}"

                results.append({
                    "file_name": file_name,
                    "comment_author": author_name,
                    "comment_body": message[:500],
                    "comment_url": comment_url,
                    "is_mention": is_mention,
                })

        except Exception:
            logger.exception("Figma polling failed for %s", file_key)

    return results


def _check_comment_on_my_page(comment: dict) -> bool:
    """댓글이 내 페이지(node)에 달린 것인지 확인."""
    client_meta = comment.get("client_meta")
    if not client_meta or not _my_page_node_ids:
        return False

    node_id = client_meta.get("node_id", "")
    if not node_id:
        return False

    # Figma 노드 ID는 "부모:자식" 형태
    # 페이지 노드 ID가 "14417:8640"이면,
    # 그 페이지 안의 노드는 다른 ID를 가지지만
    # stable_path에 페이지 ID가 포함될 수 있음
    stable_path = client_meta.get("stable_path", [])

    for page_id in _my_page_node_ids:
        if page_id == node_id:
            return True
        if page_id in stable_path:
            return True

    return False


_file_name_cache: dict[str, str] = {}


def _get_file_name(file_key: str, headers: dict) -> str:
    if file_key in _file_name_cache:
        return _file_name_cache[file_key]
    try:
        resp = requests.get(
            f"https://api.figma.com/v1/files/{file_key}?depth=1",
            headers=headers, timeout=15,
        )
        if resp.status_code == 200:
            name = resp.json().get("name", file_key)
            _file_name_cache[file_key] = name
            return name
    except Exception:
        pass
    return file_key
