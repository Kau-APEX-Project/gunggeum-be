"""앱 만들기. 같은 코드로 컨테이너 두 개를 띄움 (아키텍처 6.1: 부하 성격이 달라 분리).
  api      = create_app(rest=True)   REST (app.main)
  realtime = create_app(live=True)   WebSocket 실시간 통역 (app.live.main)
테스트는 둘 다 켠 앱 하나로 돌림."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, errors, store
from app.settings import env


def create_app(rest: bool = True, live: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool = db.make_pool()
        await app.state.pool.open(wait=False)  # DB 가 늦게 떠도 서버는 뜸 (health 는 DB 를 안 부름)
        app.state.redis = store.make_redis()
        if live:
            from app.live.pipeline import make_pipeline
            app.state.pipeline = make_pipeline(app.state.pool, app.state.redis)
        yield
        await app.state.redis.aclose()
        await app.state.pool.close()

    app = FastAPI(title='宮今 API', version=env('GIT_SHA', 'dev'), lifespan=lifespan,
                  docs_url='/api/docs' if rest else None, openapi_url='/api/openapi.json' if rest else None, redoc_url=None)
    errors.install(app)
    if origins := [o.strip() for o in env('CORS_ORIGINS').split(',') if o.strip()]:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET', 'POST', 'DELETE'],
                           allow_headers=['Content-Type', 'Authorization', 'X-Admin-Name'])
    if rest:
        from app.routes import admin, content, dev, ops, sessions
        for r in (content, sessions, ops, admin, dev):
            app.include_router(r.router)
    if live:
        from app.live import routes as live_routes
        app.include_router(live_routes.router)
    return app
