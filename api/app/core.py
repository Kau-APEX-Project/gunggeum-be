"""팀 서버 로직(vendor/gunggeum_server)을 한 번만 띄워 두고 요청마다 쓰는 곳.

vendor 모듈은 import 하는 순간 OPENAI_API_KEY·AWS 클라이언트를 요구하므로, 첫 요청 때 늦게 불러온다.
그래서 키가 없어도 서버와 /api/health 는 뜨고, 테스트는 Core 를 가짜로 바꿔 끼울 수 있다.

언어 (API 명세서 v0.1): 앱과는 ko · en · th 코드로 주고받고, 팀 로직 안에서는 '한국어' · 'English' · 'ภาษาไทย' 를 씀.
요청에 language 가 있으면 그 언어로 답하고, 없으면 팀 로직이 질문 글자로 정함 (기능 명세서 17-11 제안안).
vendor 파일은 고치지 않고 answer_language 만 감싸서 요청마다 덮어씀 (요청 스레드마다 따로인 ContextVar).
"""
import contextvars
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / 'vendor' / 'gunggeum_server'
LANG_NAME = {'ko': '한국어', 'en': 'English', 'th': 'ภาษาไทย'}
LANG_CODE = {v: k for k, v in LANG_NAME.items()}
_forced = contextvars.ContextVar('forced_language', default=None)


def use_vendor() -> None:
    """vendor 파일끼리 `from ask import ...` 처럼 서로 부르므로 폴더를 import 경로에 넣음"""
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))


def allow_forced_language(*modules) -> None:
    """모듈의 answer_language(question) 를 '정해 둔 언어가 있으면 그것, 없으면 원래 판정' 으로 바꿈.
    course.py 는 `from ask import answer_language` 로 따로 들고 있어서 두 모듈 모두 바꿈"""
    for m in modules:
        original = m.answer_language
        if getattr(original, 'forced', False):
            continue

        def answer_language(question, _original=original):
            return _forced.get() or _original(question)
        answer_language.forced = True
        m.answer_language = answer_language


@contextmanager
def answer_in(code: str | None):
    token = _forced.set(LANG_NAME[code]) if code else None
    try:
        yield
    finally:
        if token is not None:
            _forced.reset(token)


def to_code(result: dict) -> dict:
    """팀 로직 응답의 language('English') → 앱 코드('en')"""
    return {**result, 'language': LANG_CODE.get(result.get('language'), result.get('language'))}


class Core:
    """DB 연결 · 이름 색인 · 코스 재료를 들고 있는 객체. 만드는 데 몇 초 걸리므로 프로세스당 하나.

    카드는 DB만 쓰므로 먼저 준비하고, LLM 이 필요한 질문·코스(ask·course)는 처음 쓸 때 준비함.
    ask 모듈은 import 순간 OPENAI_API_KEY 를 요구하므로, 이렇게 나눠야 키가 없거나 OpenAI 가 멈춰도 카드는 동작함."""

    def __init__(self):
        use_vendor()
        import cards
        from pg import Collection

        self._cards = cards
        self.col = Collection()
        self._llm = None
        self._llm_lock = threading.Lock()

    def llm(self):
        """(ask 모듈, 이름 색인, 코스 Planner) — 첫 질문·코스 요청 때 한 번 만듦"""
        if self._llm is None:
            with self._llm_lock:
                if self._llm is None:
                    import ask
                    import course
                    allow_forced_language(ask, course)
                    self._llm = (ask, ask.name_keys(self.col), course.Planner(self.col))
        return self._llm

    def ask(self, question: str, language: str | None = None) -> dict:
        ask, names, _ = self.llm()
        with answer_in(language):
            return to_code(ask.reply(self.col, names, question)[0])

    def card(self, card_id: str) -> dict | None:
        return self._cards.card(self.col, card_id)

    def course(self, request: str, language: str | None = None) -> dict:
        _, _, planner = self.llm()
        with answer_in(language):
            return to_code(planner.make(request))


_core: Core | None = None
_lock = threading.Lock()


def get_core() -> Core:
    global _core
    if _core is None:
        with _lock:
            if _core is None:
                _core = Core()
    return _core


def core_getter():
    """FastAPI 의존성. Core 자체가 아니라 '꺼내는 함수'를 넘김 → 본문 검사(400)가 먼저 끝난 뒤에야 Core 를 만듦.
    (Core 를 바로 넘기면 키가 없을 때 잘못된 요청도 400 대신 500 이 됨)"""
    return get_core
