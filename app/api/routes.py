"""FastAPI 라우트 (OAuth 콜백, 헬스체크)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "work-bot"}


@router.get("/oauth/google/callback")
async def google_oauth_callback(code: str | None = None, error: str | None = None):
    """Google OAuth 콜백 (Calendar 인증 시 사용)."""
    if error:
        return {"error": error}
    if code:
        return {
            "message": "인증 코드를 받았습니다. 터미널에서 인증을 완료해주세요.",
            "code": code,
        }
    return {"error": "No code provided"}
