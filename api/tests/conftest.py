"""운영 DB 가 필요한 테스트용 준비물.

Postgres: TEST_PG_ADMIN_URL (기본 = docker compose 의 db, 127.0.0.1:5433) 에 gbg_test DB 를 새로 만들어 씀. 접속이 안 되면 건너뜀.
Redis: fakeredis (메모리). 번역은 echo, 음성 인식은 끔, 해설사 문장 직접 입력(ALLOW_TEXT_INPUT) 켬.
"""
import os

import fakeredis
import psycopg
import pytest
from fastapi.testclient import TestClient

ADMIN = os.environ.get('TEST_PG_ADMIN_URL', 'postgresql://postgres:gbg@127.0.0.1:5433/postgres')
TABLES = 'live_session, session_language, session_card_mention, tour_schedule, notice, notice_translation, visit_stat'
# 카드 링크 테스트용 전각 하나 (실제 docs 테이블 대신)
METAS = [{'type': 'building', 'serial': 160, 'name': '근정전', 'name_en': 'Geunjeongjeon (Throne Hall)'}]


@pytest.fixture(scope='session')
def pg_url():
    try:
        with psycopg.connect(ADMIN, autocommit=True, connect_timeout=3) as c:
            c.execute('drop database if exists gbg_test with (force)')
            c.execute('create database gbg_test')
    except psycopg.OperationalError:
        pytest.skip('테스트용 Postgres 에 접속할 수 없음 (docker compose up -d db)')
    return ADMIN.rsplit('/', 1)[0] + '/gbg_test'


@pytest.fixture
def client(pg_url, monkeypatch):
    from app import store
    from app.db import SCHEMA
    from app.factory import create_app
    from app.live.pipeline import Linker

    for k, v in {'DATABASE_URL': pg_url, 'TRANSLATE_PROVIDER': 'echo', 'STT_PROVIDER': 'none',
                 'ALLOW_TEXT_INPUT': '1', 'PUBLIC_BASE_URL': 'https://example.test'}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv('GUIDE_ACCESS_CODE', raising=False)
    with psycopg.connect(pg_url, autocommit=True) as c:
        c.execute(SCHEMA)
        c.execute(f'truncate {TABLES} cascade')

    server = fakeredis.FakeServer()
    monkeypatch.setattr(store, 'make_redis', lambda: fakeredis.FakeAsyncRedis(server=server, decode_responses=True))

    async def load(self):
        return METAS
    monkeypatch.setattr(Linker, 'load', load)

    with TestClient(create_app(rest=True, live=True)) as c:
        yield c


@pytest.fixture
def sql(pg_url):
    """테스트에서 DB 를 직접 보거나 넣을 때"""
    with psycopg.connect(pg_url, autocommit=True, row_factory=psycopg.rows.dict_row) as c:
        yield c
