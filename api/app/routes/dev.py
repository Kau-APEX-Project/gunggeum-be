"""개발용 도구. DEV_TOOLS=1 일 때만 열림 (운영에서는 404).

  GET /api/dev/live-tester   라이브 투어 브라우저 테스트 페이지 — 세션 REST 4개 + WebSocket 2개를 한 화면에서
"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.errors import ApiError
from app.settings import flag

router = APIRouter(prefix='/api/dev', include_in_schema=False)
TESTER = Path(__file__).resolve().parents[1] / 'static' / 'live-tester.html'


@router.get('/live-tester', response_class=HTMLResponse)
def live_tester():
    if not flag('DEV_TOOLS'):
        raise ApiError(404, '없는 경로')
    return HTMLResponse(TESTER.read_text(encoding='utf-8'))
