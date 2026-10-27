"""api 컨테이너: REST 엔드포인트 전부 (uvicorn app.main:app)"""
from app.factory import create_app

app = create_app(rest=True)
