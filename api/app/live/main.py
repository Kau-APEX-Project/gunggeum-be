"""realtime 컨테이너: 라이브 투어 WebSocket (uvicorn app.live.main:app --port 8001)"""
from app.factory import create_app

app = create_app(rest=False, live=True)
