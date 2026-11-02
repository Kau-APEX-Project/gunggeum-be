"""운영 데이터 엔드포인트 (API 명세서 v0.1 6.2 · 6.3 · 7.1).

  GET  /api/tours/today    오늘 해설 일정 (T-30)
  GET  /api/notices        공지 목록 (T-10 배너 · T-50)
  POST /api/stats/visits   방문 익명 집계 (T-51)

일정·공지는 운영자가 `python -m app.cli` 로 넣음 (자동 수집 배치는 수집 대상이 정해지면 추가)."""
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from app.deps import db
from app.errors import ApiError
from app.settings import KST, iso, now

router = APIRouter(prefix='/api')


@router.get('/tours/today')
async def tours_today(pool=Depends(db)):
    t = now()
    async with pool.connection() as c:
        rows = await (await c.execute(
            'select s.start_time, s.duration_min, s.session_code, l.status from tour_schedule s '
            'left join live_session l on l.code = s.session_code where s.tour_date = %s order by s.start_time',
            (t.date(),))).fetchall()
    tours = []
    for x in rows:
        start = datetime.combine(t.date(), x['start_time'], KST)
        if x['status'] in ('live', 'ended'):  # 앱 세션이 있으면 세션 상태를 따름
            status = x['status']
        else:  # 세션이 없거나 아직 해설사가 안 붙음: 시간으로만 판단
            status = 'ended' if t >= start + timedelta(minutes=x['duration_min']) else 'upcoming'
        tours.append({'time': x['start_time'].strftime('%H:%M'), 'status': status,
                      'sessionCode': x['session_code'] if status == 'live' else None})
    return {'date': t.date().isoformat(), 'tours': tours}


@router.get('/notices')
async def notices(lang: Literal['en', 'th', 'ko'] = 'en', since: datetime | None = None, pool=Depends(db)):
    """번역이 있으면 그 언어, 없으면 한국어 원문 (lang 필드로 구분)"""
    sql = ('select n.id, n.type, n.published_at, coalesce(t.title, n.title) as title, coalesce(t.body, n.body) as body, '
           "case when t.title is null then 'ko' else t.lang end as lang "
           'from notice n left join notice_translation t on t.notice_id = n.id and t.lang = %s')
    args: list = [lang]
    if since:
        sql += ' where n.published_at > %s'
        args.append(since if since.tzinfo else since.replace(tzinfo=KST))
    async with pool.connection() as c:
        rows = await (await c.execute(sql + ' order by n.published_at desc limit 20', args)).fetchall()
    return {'notices': [{'id': x['id'], 'type': x['type'], 'title': x['title'], 'body': x['body'],
                         'publishedAt': iso(x['published_at']), 'lang': x['lang']} for x in rows]}


class VisitIn(BaseModel):
    poiId: str = Field(pattern=r'^[\w:.\-]{1,80}$')  # pois.json 의 id
    event: Literal['audio', 'stamp']
    lang: Literal['en', 'th', 'ko']
    date: date


@router.post('/stats/visits', status_code=204)
async def visit(body: VisitIn, pool=Depends(db)):
    """사용자 식별자·좌표·정확한 시각 없이 날짜·POI·언어·사건별 합계만 +1"""
    if abs((body.date - now().date()).days) > 1:
        raise ApiError(400, 'date 는 오늘 기준 ±1일만 받습니다')
    async with pool.connection() as c:
        await c.execute('insert into visit_stat values (%s, %s, %s, %s, 1) on conflict (stat_date, poi_id, lang, event) '
                        'do update set count = visit_stat.count + 1', (body.date, body.poiId, body.lang, body.event))
    return Response(status_code=204)
