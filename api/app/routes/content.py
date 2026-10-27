"""팀 로직(질문·카드·코스)을 HTTP 로 감싼 엔드포인트. 계약은 API 명세서 v0.1 (2·3·4·6.1절).

  POST /api/ask      질문 · 길 묻기 · 근처 편의시설
  GET  /api/card     카드 한 장
  POST /api/course   테마 코스
  GET  /api/health   배포 확인 (DB·LLM 안 부름)
"""
from typing import Literal

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

    @field_validator('question')
    @classmethod
    def _question(cls, v: str) -> str:
        return clean(v)


class CourseIn(BaseModel):
    request: str
    language: Lang | None = None

    @field_validator('request')
    @classmethod
    def _request(cls, v: str) -> str:
        return clean(v)


@router.get('/health')
def health():
    return {'status': 'ok', 'version': env('GIT_SHA', 'dev')}


@router.post('/ask')
async def ask(body: AskIn, core=Depends(core_getter)):
    return await run_in_threadpool(lambda: core().ask(body.question, body.language))


@router.get('/card')
async def card(id: str = Query(min_length=1), core=Depends(core_getter)):
    c = await run_in_threadpool(lambda: core().card(id))
    if c is None:
        return error(404, '없는 카드')
    # 카드 내용은 문서 배치로만 바뀜 → CloudFront·폰이 하루 캐시해도 됨
    return JSONResponse(c, headers={'Cache-Control': 'public, max-age=86400'})


@router.post('/course')
async def course(body: CourseIn, core=Depends(core_getter)):
    return await run_in_threadpool(lambda: core().course(body.request, body.language))
