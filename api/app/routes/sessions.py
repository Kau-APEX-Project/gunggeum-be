"""라이브 투어 세션 (API 명세서 v0.1 7.2~7.5, 화면 G-01~G-04 · T-31 · T-32).

  POST /api/sessions                  세션 만들기 (해설사)
  GET  /api/sessions/{code}           세션 정보
  POST /api/sessions/{code}/end       세션 종료 (Authorization: Bearer <guideToken>)
  GET  /api/sessions/{code}/summary   세션 요약 (집계값과 카드 id 만)

정해지지 않은 것은 제안안으로 구현: 가이드 접근 제어 = 환경 변수 GUIDE_ACCESS_CODE 하나 (비우면 검사 안 함, 기능 명세서 17-1)."""
import hashlib
import hmac
import re
import secrets

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from app import store
from app.deps import db, rds
from app.errors import ApiError
from app.settings import env, iso, now

router = APIRouter(prefix='/api/sessions')
CODE = re.compile(r'GB-\d{4}')


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_ok(row: dict, token: str) -> bool:
    return bool(token) and hmac.compare_digest(hash_token(token), row['guide_token_hash'])


async def fetch(pool, code: str) -> dict | None:
    if not CODE.fullmatch(code or ''):
        return None
    async with pool.connection() as c:
        return await (await c.execute('select * from live_session where code = %s', (code,))).fetchone()


async def must_fetch(pool, code: str) -> dict:
    row = await fetch(pool, code)
    if row is None:
        raise ApiError(404, '없는 세션')
    return row


async def mark_live(pool, r, code: str) -> None:
    """해설사가 WebSocket 에 처음 붙으면 waiting → live"""
    async with pool.connection() as c:
        await c.execute("update live_session set status = 'live' where code = %s and status = 'waiting'", (code,))
    await store.set_status(r, code, 'live')


async def summary(pool, r, row: dict) -> dict:
    code = row['code']
    if row['status'] == 'ended':
        async with pool.connection() as c:
            langs = await (await c.execute('select lang, peak_count from session_language where session_code = %s', (code,))).fetchall()
            cards = await (await c.execute('select card_id from session_card_mention where session_code = %s '
                                           'order by count desc, card_id', (code,))).fetchall()
        peak, languages, mentioned, end = (row['peak_participants'], {x['lang']: x['peak_count'] for x in langs},
                                           [x['card_id'] for x in cards], row['ended_at'])
    else:
        peak, languages = await store.peaks(r, code)
        counts = await store.card_counts(r, code)
        mentioned, end = sorted(counts, key=lambda k: (-counts[k], k)), now()
    return {'code': code, 'durationSec': max(0, int((end - row['started_at']).total_seconds())),
            'peakParticipants': peak, 'languages': languages, 'mentionedCards': mentioned}


class SessionIn(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    consent: bool
    guideName: str | None = Field(default=None, max_length=40)
    accessCode: str | None = Field(default=None, max_length=100)
    tourTime: str | None = Field(default=None, pattern=r'^\d{2}:\d{2}$')  # 추가 제안: 오늘 해설 일정(T-30)에 연결


@router.post('', status_code=201)
async def create(body: SessionIn, pool=Depends(db), r=Depends(rds)):
    if not body.consent:
        raise ApiError(400, '음성 미저장 동의(consent)가 필요합니다')
    expected = env('GUIDE_ACCESS_CODE')
    if expected and not hmac.compare_digest((body.accessCode or '').encode(), expected.encode()):
        raise ApiError(403, '가이드 접근 코드가 올바르지 않습니다')

    token, started = secrets.token_urlsafe(32), now()
    async with pool.connection() as c:
        for _ in range(20):  # GB-1000~9999, 겹치면 다시 뽑음
            code = f'GB-{secrets.randbelow(9000) + 1000}'
            row = await (await c.execute(
                'insert into live_session (code, title, guide_name, guide_token_hash, consent, started_at) '
                'values (%s, %s, %s, %s, true, %s) on conflict (code) do nothing returning code',
                (code, body.title, body.guideName, hash_token(token), started))).fetchone()
            if row:
                break
        else:
            raise ApiError(503, '세션 코드를 만들지 못했습니다')
        if body.tourTime:
            await c.execute('update tour_schedule set session_code = %s where tour_date = %s and start_time = %s::time',
                            (code, started.date(), body.tourTime))
    await store.init_session(r, code, iso(started), body.guideName)
    base = env('PUBLIC_BASE_URL', 'http://localhost:5173').rstrip('/')
    return {'code': code, 'joinUrl': f'{base}/live/{code}', 'guideToken': token, 'sourceLang': 'ko', 'startedAt': iso(started)}


@router.get('/{code}')
async def info(code: str, pool=Depends(db), r=Depends(rds)):
    row = await must_fetch(pool, code)
    return {'code': code, 'title': row['title'], 'guideName': row['guide_name'], 'status': row['status'],
            'startedAt': iso(row['started_at']), 'micOn': row['status'] != 'ended' and await store.mic_on(r, code)}


@router.post('/{code}/end')
async def end(code: str, authorization: str | None = Header(default=None), pool=Depends(db), r=Depends(rds)):
    row = await must_fetch(pool, code)
    token = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    if not token_ok(row, token):
        raise ApiError(401, '가이드 토큰이 필요합니다')
    if row['status'] != 'ended':
        peak, languages = await store.peaks(r, code)
        counts = await store.card_counts(r, code)
        async with pool.connection() as c, c.transaction():
            row = await (await c.execute(
                "update live_session set status = 'ended', ended_at = %s, peak_participants = %s where code = %s returning *",
                (now(), peak, code))).fetchone()
            for lang, n in languages.items():
                await c.execute('insert into session_language values (%s, %s, %s) on conflict do nothing', (code, lang, n))
            for cid, n in counts.items():
                await c.execute('insert into session_card_mention values (%s, %s, %s) on conflict do nothing', (code, cid, n))
        await store.close_session(r, code)
    return await summary(pool, r, row)


@router.get('/{code}/summary')
async def get_summary(code: str, pool=Depends(db), r=Depends(rds)):
    return await summary(pool, r, await must_fetch(pool, code))
