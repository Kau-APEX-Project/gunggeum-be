"""라우터가 쓰는 의존성: DB 풀 · Redis (앱 시작 때 app.state 에 만들어 둠)"""
from fastapi import Request
from psycopg_pool import AsyncConnectionPool

from app.db import ensure_schema


async def db(request: Request) -> AsyncConnectionPool:
    return await ensure_schema(request.app.state.pool)


def rds(request: Request):
    return request.app.state.redis
