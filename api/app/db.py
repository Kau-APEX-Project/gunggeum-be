"""운영 DB (ERD v0.1 5절): 공지 · 해설 일정 · 라이브 세션 · 익명 집계.
콘텐츠 DB(docs 테이블, 팀 로직이 씀)와 같은 Postgres 안의 별도 테이블. 처음 쓸 때 한 번 만듦 (create if not exists)."""
import os
import weakref

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

SCHEMA = """
create table if not exists live_session (
  code              text primary key,                -- GB-1042
  title             text,
  guide_name        text,
  guide_token_hash  text not null,                   -- 가이드 토큰은 해시만 저장
  consent           boolean not null,                -- 음성 미저장 동의
  source_lang       text not null default 'ko',
  status            text not null default 'waiting' check (status in ('waiting', 'live', 'ended')),
  started_at        timestamptz not null,
  ended_at          timestamptz,
  peak_participants int not null default 0
);
create table if not exists session_language (        -- 세션 종료 시 Redis 최대 동시 참여 언어 분포를 옮김
  session_code text references live_session(code) on delete cascade,
  lang         text,
  peak_count   int not null,
  primary key (session_code, lang)
);
create table if not exists session_card_mention (    -- 자막 원문 대신 언급된 카드 id 만 집계 (T-32)
  session_code text references live_session(code) on delete cascade,
  card_id      text,
  count        int not null,
  primary key (session_code, card_id)
);
create table if not exists tour_schedule (           -- 운영자가 입력 (관리자 API 또는 app.cli tours add)
  id           serial primary key,
  tour_date    date not null,
  start_time   time not null,
  duration_min int not null default 60,
  session_code text references live_session(code) on delete set null,
  unique (tour_date, start_time)
);
create table if not exists notice (
  id           text primary key,                     -- n-20261021-01
  type         text not null check (type in ('tour_cancelled', 'weather', 'event_change')),
  title        text not null,                        -- 한국어 원문
  body         text not null,
  source_url   text unique,                          -- 원문 URL 로 중복 수집 방지
  published_at timestamptz not null,
  collected_at timestamptz not null default now()
);
create table if not exists notice_translation (
  notice_id text references notice(id) on delete cascade,
  lang      text check (lang in ('en', 'th')),
  title     text not null,
  body      text not null,
  primary key (notice_id, lang)
);
create table if not exists visit_stat (              -- 날짜·POI·언어·사건 단위 합계만. 사용자 식별자·좌표 없음
  stat_date date,
  poi_id    text,
  lang      text,
  event     text,
  count     int not null default 0,
  primary key (stat_date, poi_id, lang, event)
);
-- 관리자 API: 누가(X-Admin-Name) 언제 넣었는지. 먼저 만든 테이블에도 붙도록 add column if not exists
alter table notice        add column if not exists created_by text;
alter table tour_schedule add column if not exists created_by text;
alter table tour_schedule add column if not exists created_at timestamptz not null default now();
"""

_ready: "weakref.WeakSet[AsyncConnectionPool]" = weakref.WeakSet()


def make_pool() -> AsyncConnectionPool:
    return AsyncConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=5, open=False, timeout=10,
                               kwargs={'autocommit': True, 'row_factory': dict_row})


async def ensure_schema(pool: AsyncConnectionPool) -> AsyncConnectionPool:
    """처음 쓸 때 테이블을 만듦. api 워커 여러 개·realtime 이 동시에 떠도 겹치지 않게 advisory lock"""
    if pool not in _ready:
        async with pool.connection() as c:
            await c.execute('select pg_advisory_lock(7042)')
            try:
                await c.execute(SCHEMA)
            finally:
                await c.execute('select pg_advisory_unlock(7042)')
        _ready.add(pool)
    return pool
