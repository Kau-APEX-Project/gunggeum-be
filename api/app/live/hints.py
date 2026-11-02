"""위치별 사전 (STT 벤치마크 v2 4.1): 해설 위치마다 그 구역 해설에 나오는 전각명·용어 목록.

받아쓰기 사전(Whisper initial_prompt · Transcribe 위치별 어휘)과 후처리 사전이 같은 목록을 씀.
파일: STT_HINTS_PATH (JSON {"<poiId>": ["근정전", "월대", ...], ...}).
원본은 AI 담당의 STT학습데이터/Benchmark/data/hints_by_location.json (prepare.py 생성) — 키를 pois.json 의 id 로 맞춰 변환해 넣음.
파일이 없으면 사전 없이 받아씀 (전각명 인식률이 크게 떨어지므로 운영에서는 꼭 넣을 것).
"""
import json
import logging
from pathlib import Path

from app.settings import env

log = logging.getLogger('gunggeum.stt')
PROMPT_HEAD = '경복궁 해설입니다.'  # 벤치마크와 같은 앞 문장
PROMPT_MAX_CHARS = 400  # Whisper initial_prompt 223토큰 제한 안쪽으로 (위치별 5~26개면 충분히 들어감)


class Hints:
    def __init__(self, by_location: dict[str, list[str]]):
        self.by_location = by_location

    @classmethod
    def load(cls) -> 'Hints':
        path = env('STT_HINTS_PATH')
        if not path:
            return cls({})
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            return cls({str(k): [str(t) for t in v] for k, v in data.items() if not str(k).startswith('_')})
        except (OSError, ValueError, AttributeError):
            log.exception('위치별 사전을 읽지 못함: %s (사전 없이 진행)', path)
            return cls({})

    def terms(self, location: str | None) -> list[str]:
        return self.by_location.get(location or '', [])

    def prompt(self, location: str | None) -> str:
        """Whisper initial_prompt: '경복궁 해설입니다. 근정전, 월대, …' — 위치를 모르면 앞 문장만"""
        terms = self.terms(location)
        text = f"{PROMPT_HEAD} {', '.join(terms)}." if terms else PROMPT_HEAD
        return text[:PROMPT_MAX_CHARS]
