"""팀 로직(질문·카드·코스)을 HTTP 로 감싼 엔드포인트. 계약은 API 명세서 v0.1 (2·3·4·6.1절).

  POST /api/ask      질문 · 길 묻기 · 근처 편의시설 · 코스 요청 (후속 질문 history, 지금 위치 here, 코스 출발 nearest)
  GET  /api/card     카드 한 장
  POST /api/course   테마 코스 (nearest 권역에서 출발)
  GET  /api/health   배포 확인 (DB·LLM 안 부름)
"""
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from starlette.concurrency import run_in_threadpool

from app.core import core_getter
from app.errors import error
from app.settings import env

MAX_CHARS = 300  # API 명세서 2.1·4.1: 1~300자, 넘으면 400 (글자 수 기준)
Lang = Literal['ko', 'en', 'th']

router = APIRouter(prefix='/api')


def clean(v: str) -> str:
    v = v.strip()
    if not v or len(v) > MAX_CHARS:
        raise ValueError(f'1~{MAX_CHARS}자')
    return v


class AskIn(BaseModel):
    question: str
    language: Lang | None = None  # 초안 필드 (A1): 보내면 그 언어로, 없으면 질문으로 판정
    # 아래 셋은 llm-gps API.md §2 그대로. 형식 검사(틀린 history 항목 버림·최근 3개·question 300자,
    # 모르는 POI id 무시)는 ask.reply 가 하므로 여기서는 받은 값을 그대로 넘김 (틀린 값도 400 아님)
    history: Any = None   # 이전 턴 [{question, answer}] — 후속 질문("거기는 누가 살았어?")
    here: Any = None      # 지금 있는 곳 POI id (폰 judge.where(), 전각 30m 안일 때만) — "여기 뭐야?"
    nearest: Any = None   # 가장 가까운 POI id (폰 judge.where(Infinity)) — 질문이 코스 요청일 때 출발 권역

    @field_validator('question')
    @classmethod
    def _question(cls, v: str) -> str:
        return clean(v)


class CourseIn(BaseModel):
    request: str
    language: Lang | None = None
    nearest: Any = None   # 가장 가까운 POI id → 그 권역에서 출발·도착. 없으면 here, 둘 다 없거나 모르는 id 면 광화문
    here: Any = None

    @field_validator('request')
    @classmethod
    def _request(cls, v: str) -> str:
        return clean(v)


@router.get('/health')
def health():
    return {'status': 'ok', 'version': env('GIT_SHA', 'dev')}


@router.post('/ask')
async def ask(body: AskIn, core=Depends(core_getter)):
    return await run_in_threadpool(lambda: core().ask(body.question, body.language,
                                                      history=body.history, here=body.here, nearest=body.nearest))


@router.get('/card')
async def card(id: str = Query(min_length=1), core=Depends(core_getter)):
    c = await run_in_threadpool(lambda: core().card(id))
    if c is None:
        return error(404, '없는 카드')
    # 카드 내용은 문서 배치로만 바뀜 → CloudFront·폰이 하루 캐시해도 됨
    return JSONResponse(c, headers={'Cache-Control': 'public, max-age=86400'})


@router.post('/course')
async def course(body: CourseIn, core=Depends(core_getter)):
    return await run_in_threadpool(lambda: core().course(body.request, body.language, here=body.nearest or body.here))
