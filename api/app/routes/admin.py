"""운영자 API: 공지 · 해설 일정 입력 (관리자 화면이 생기기 전에는 /api/docs 에서 직접 호출).

  POST   /api/admin/notices              공지 추가 (번역 직접 입력 또는 Translate 자동 번역)
  GET    /api/admin/notices              공지 목록 (번역 언어 · 입력자 포함)
  DELETE /api/admin/notices/{id}         공지 삭제
  GET    /api/admin/notice-drafts        자동 수집한 공지 초안 (?status=pending · approved · rejected)
  POST   /api/admin/notice-drafts/{id}/preview   저장하지 않고 번역만 해 보기
  POST   /api/admin/notice-drafts/{id}/approve   영어·태국어를 확인해 넣고 공개
  POST   /api/admin/notice-drafts/{id}/reject    거절
  POST   /api/admin/tours                해설 일정 추가 (한 날짜에 여러 시각)
  GET    /api/admin/tours?date=          그 날짜 일정 (연결된 세션 포함)
  DELETE /api/admin/tours?date=&time=    일정 하나 삭제

인증: Authorization: Bearer <ADMIN_TOKEN> (서버 환경 변수). 비어 있으면 관리자 API 는 꺼짐.
가이드 접근 코드와 별도 — 해설사는 공지·일정을 바꿀 수 없음.
누가 넣었는지는 X-Admin-Name 헤더(선택)로 남김. 토큰을 아는 사람은 모두 같은 권한."""
import hmac
import logging
import re
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field, field_validator

from app.deps import db
from app.errors import ApiError
from app.settings import env, iso, now

log = logging.getLogger('gunggeum.admin')
TIME = re.compile(r'([01]\d|2[0-3]):[0-5]\d')


def admin(authorization: str | None = Header(default=None),
          x_admin_name: str | None = Header(default=None, max_length=40)) -> str:
    """관리자 토큰 확인 → 입력자 이름(없으면 'admin')"""
    expected = env('ADMIN_TOKEN')
    if not expected:
        raise ApiError(403, '관리자 기능이 꺼져 있습니다')
    token = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    if not hmac.compare_digest(token.encode(), expected.encode()):
        raise ApiError(401, '관리자 토큰이 필요합니다')
    return (x_admin_name or 'admin').strip() or 'admin'


router = APIRouter(prefix='/api/admin', dependencies=[Depends(admin)])


# ---------- 공지 ----------

class Text(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)


class NoticeIn(Text):
    type: Literal['tour_cancelled', 'weather', 'event_change']
    url: str | None = Field(default=None, max_length=500)  # 원문 URL (같은 공지 중복 방지)
    translations: dict[Literal['en', 'th'], Text] = {}     # 직접 입력한 번역
    translate: bool = False                                 # 빠진 언어를 Amazon Translate 로 채움


async def translate_missing(body: NoticeIn) -> dict[str, Text]:
    out = dict(body.translations)
    if body.translate:
        from app.live.translate import make_translator
        t = make_translator()
        for lang in ('en', 'th'):
            if lang not in out:
                out[lang] = Text(title=await t.translate(body.title, lang, notice=True),
                                 body=await t.translate(body.body, lang, notice=True))
    return out


async def notice_rows(pool, notice_id: str | None = None) -> list[dict]:
    sql = ('select n.id, n.type, n.title, n.body, n.source_url, n.published_at, n.created_by, '
           "coalesce(jsonb_object_agg(t.lang, jsonb_build_object('title', t.title, 'body', t.body)) "
           "filter (where t.lang is not null), '{}') as translations "
           'from notice n left join notice_translation t on t.notice_id = n.id')
    args: list = []
    if notice_id:
        sql += ' where n.id = %s'
        args.append(notice_id)
    async with pool.connection() as c:
        rows = await (await c.execute(sql + ' group by n.id order by n.published_at desc limit 100', args)).fetchall()
    return [{'id': x['id'], 'type': x['type'], 'title': x['title'], 'body': x['body'], 'url': x['source_url'],
             'publishedAt': iso(x['published_at']), 'createdBy': x['created_by'], 'translations': x['translations']}
            for x in rows]


async def insert_notice(c, body: 'NoticeIn | ApproveIn', translations: dict[str, Text], url: str | None, who: str) -> str:
    t = now()
    if url and await (await c.execute('select 1 from notice where source_url = %s', (url,))).fetchone():
        raise ApiError(409, '같은 원문 URL 의 공지가 이미 있습니다')
    prefix = f"n-{t:%Y%m%d}-"
    n = (await (await c.execute("select coalesce(max(split_part(id, '-', 3)::int), 0) as n from notice where id like %s", (prefix + '%',))).fetchone())['n']
    nid = f'{prefix}{n + 1:02d}'  # 가장 큰 번호 + 1 (개수 + 1 이면 지운 뒤 번호가 겹침)
    await c.execute('insert into notice (id, type, title, body, source_url, published_at, created_by) '
                    'values (%s, %s, %s, %s, %s, %s, %s)', (nid, body.type, body.title, body.body, url, t, who))
    for lang, tr in translations.items():
        await c.execute('insert into notice_translation values (%s, %s, %s, %s)', (nid, lang, tr.title, tr.body))
    return nid


@router.post('/notices', status_code=201)
async def add_notice(body: NoticeIn, who: str = Depends(admin), pool=Depends(db)):
    translations = await translate_missing(body)
    async with pool.connection() as c, c.transaction():
        nid = await insert_notice(c, body, translations, body.url, who)
    log.info('공지 추가 %s by %s', nid, who)
    return (await notice_rows(pool, nid))[0]


@router.get('/notices')
async def list_notices(pool=Depends(db)):
    return {'notices': await notice_rows(pool)}


@router.delete('/notices/{notice_id}', status_code=204)
async def delete_notice(notice_id: str, who: str = Depends(admin), pool=Depends(db)):
    async with pool.connection() as c:
        row = await (await c.execute('delete from notice where id = %s returning id', (notice_id,))).fetchone()
    if row is None:
        raise ApiError(404, '없는 공지')
    log.info('공지 삭제 %s by %s', notice_id, who)
    return Response(status_code=204)


# ---------- 공지 초안 (자동 수집 → 승인) ----------

class ApproveIn(Text):
    """title·body 는 운영자가 쓴 한국어 제목·요약 (원문을 그대로 옮기지 않음)"""
    type: Literal['tour_cancelled', 'weather', 'event_change']
    en: Text  # 확인한 번역. 둘 다 있어야 공개
    th: Text


def draft_json(x: dict) -> dict:
    return {'id': x['id'], 'title': x['title'], 'date': x['notice_date'].isoformat(), 'url': x['source_url'],
            'status': x['status'], 'noticeId': x['notice_id'], 'collectedAt': iso(x['collected_at']),
            'decidedBy': x['decided_by'], 'decidedAt': iso(x['decided_at'])}


async def decide(c, draft_id: str, status: str, who: str) -> dict:
    """대기 중인 초안만 처리. 두 사람이 동시에 눌러도 한 번만 됨"""
    row = await (await c.execute("update notice_draft set status = %s, decided_by = %s, decided_at = now() "
                                 "where id = %s and status = 'pending' returning *", (status, who, draft_id))).fetchone()
    if row is None:
        seen = await (await c.execute('select 1 from notice_draft where id = %s', (draft_id,))).fetchone()
        raise ApiError(409, '이미 처리한 초안입니다') if seen else ApiError(404, '없는 초안')
    return row


@router.get('/notice-drafts')
async def list_drafts(status: Literal['pending', 'approved', 'rejected'] = 'pending', pool=Depends(db)):
    async with pool.connection() as c:
        rows = await (await c.execute('select * from notice_draft where status = %s '
                                      'order by notice_date desc, id desc limit 100', (status,))).fetchall()
        run = await (await c.execute('select * from notice_collect where id = 1')).fetchone()
    run = run or {'last_ok_at': None, 'last_error': None, 'last_error_at': None}
    return {'drafts': [draft_json(x) for x in rows],
            'collect': {'lastOkAt': iso(run['last_ok_at']), 'lastError': run['last_error'],
                        'lastErrorAt': iso(run['last_error_at'])}}


@router.post('/notice-drafts/{draft_id}/preview')
async def preview_draft(draft_id: str, body: Text, pool=Depends(db)):
    """운영자가 쓴 제목·요약을 영어·태국어로 번역해 돌려줌 (저장하지 않음)"""
    async with pool.connection() as c:
        if not await (await c.execute('select 1 from notice_draft where id = %s', (draft_id,))).fetchone():
            raise ApiError(404, '없는 초안')
    return await translate_missing(NoticeIn(type='event_change', title=body.title, body=body.body, translate=True))


@router.post('/notice-drafts/{draft_id}/approve', status_code=201)
async def approve_draft(draft_id: str, body: ApproveIn, who: str = Depends(admin), pool=Depends(db)):
    async with pool.connection() as c, c.transaction():
        row = await decide(c, draft_id, 'approved', who)
        nid = await insert_notice(c, body, {'en': body.en, 'th': body.th}, row['source_url'], who)
        await c.execute('update notice_draft set notice_id = %s where id = %s', (nid, draft_id))
    log.info('공지 초안 승인 %s -> %s by %s', draft_id, nid, who)
    return (await notice_rows(pool, nid))[0]


@router.post('/notice-drafts/{draft_id}/reject')
async def reject_draft(draft_id: str, who: str = Depends(admin), pool=Depends(db)):
    async with pool.connection() as c, c.transaction():
        row = await decide(c, draft_id, 'rejected', who)
    log.info('공지 초안 거절 %s by %s', draft_id, who)
    return draft_json(row)


# ---------- 해설 일정 ----------

class ToursIn(BaseModel):
    date: date
    times: list[str] = Field(min_length=1, max_length=24)  # ["10:00", "14:00"]
    durationMin: int = Field(default=60, ge=10, le=240)

    @field_validator('times')
    @classmethod
    def _times(cls, v: list[str]) -> list[str]:
        if not all(TIME.fullmatch(x) for x in v):
            raise ValueError('HH:MM')
        return sorted(set(v))


async def tour_rows(pool, day: date) -> list[dict]:
    async with pool.connection() as c:
        rows = await (await c.execute(
            'select start_time, duration_min, session_code, created_by from tour_schedule where tour_date = %s '
            'order by start_time', (day,))).fetchall()
    return [{'time': x['start_time'].strftime('%H:%M'), 'durationMin': x['duration_min'],
             'sessionCode': x['session_code'], 'createdBy': x['created_by']} for x in rows]


@router.post('/tours', status_code=201)
async def add_tours(body: ToursIn, who: str = Depends(admin), pool=Depends(db)):
    """같은 날짜·시각이 이미 있으면 해설 길이만 바꿈"""
    if body.date < now().date():
        raise ApiError(400, '지난 날짜에는 일정을 넣을 수 없습니다')
    async with pool.connection() as c, c.transaction():
        for t in body.times:
            await c.execute('insert into tour_schedule (tour_date, start_time, duration_min, created_by) '
                            'values (%s, %s::time, %s, %s) on conflict (tour_date, start_time) '
                            'do update set duration_min = excluded.duration_min, created_by = excluded.created_by',
                            (body.date, t, body.durationMin, who))
    log.info('일정 추가 %s %s by %s', body.date, body.times, who)
    return {'date': body.date.isoformat(), 'tours': await tour_rows(pool, body.date)}


@router.get('/tours')
async def list_tours(day: date = Query(alias='date'), pool=Depends(db)):
    return {'date': day.isoformat(), 'tours': await tour_rows(pool, day)}


@router.delete('/tours', status_code=204)
async def delete_tour(day: date = Query(alias='date'), time: str = Query(pattern=r'^([01]\d|2[0-3]):[0-5]\d$'),
                      who: str = Depends(admin), pool=Depends(db)):
    async with pool.connection() as c:
        row = await (await c.execute('delete from tour_schedule where tour_date = %s and start_time = %s::time returning id',
                                     (day, time))).fetchone()
    if row is None:
        raise ApiError(404, '없는 일정')
    log.info('일정 삭제 %s %s by %s', day, time, who)
    return Response(status_code=204)
