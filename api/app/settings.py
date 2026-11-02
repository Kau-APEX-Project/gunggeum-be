"""환경 변수와 공통 상수. 값은 부를 때마다 읽어서 테스트가 바꿔 끼울 수 있게 함"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
LANGS = ('en', 'th', 'ko')  # 앱 언어 코드 (API 명세서 v0.1 · 라이브 투어 · 공지 · 집계)


def env(name: str, default: str = '') -> str:
    return os.environ.get(name, default)


def flag(name: str) -> bool:
    return env(name).lower() in ('1', 'true', 'yes')


def now() -> datetime:
    return datetime.now(KST)


def iso(dt: datetime | None) -> str | None:
    """2026-10-21T14:00:00+09:00 형식 (API 명세서 1.2)"""
    return dt.astimezone(KST).isoformat(timespec='seconds') if dt else None
