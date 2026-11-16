"""팀 로직 언어 연결 (vendor 를 고치지 않고 language 요청 필드를 반영)"""
import threading
import types

from app.core import Core, allow_forced_language, answer_in, to_code


def fake_modules():
    ask = types.SimpleNamespace(answer_language=lambda q: '한국어' if any('가' <= c <= '힣' for c in q) else 'English')
    course = types.SimpleNamespace(answer_language=ask.answer_language)  # `from ask import answer_language` 흉내
    allow_forced_language(ask, course)
    return ask, course


def test_default_uses_question():
    ask, course = fake_modules()
    assert ask.answer_language('강녕전') == '한국어' and course.answer_language('hello') == 'English'


def test_forced_language_applies_and_resets():
    ask, course = fake_modules()
    with answer_in('th'):
        assert ask.answer_language('강녕전') == 'ภาษาไทย' and course.answer_language('hello') == 'ภาษาไทย'
    assert ask.answer_language('강녕전') == '한국어'


def test_wrapping_twice_is_harmless():
    ask, _ = fake_modules()
    allow_forced_language(ask)
    with answer_in('en'):
        assert ask.answer_language('강녕전') == 'English'


def test_forced_language_is_per_thread():
    ask, _ = fake_modules()
    seen, ready = {}, threading.Barrier(2)

    def run(code, q):
        with answer_in(code):
            ready.wait()
            seen[code] = ask.answer_language(q)
    threads = [threading.Thread(target=run, args=('th', '강녕전')), threading.Thread(target=run, args=(None, '강녕전'))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {'th': 'ภาษาไทย', None: '한국어'}


def test_to_code():
    assert to_code({'answer': 'x', 'language': 'ภาษาไทย'})['language'] == 'th'
    assert to_code({'answer': 'x', 'language': 'English', 'action': None}) == {'answer': 'x', 'language': 'en', 'action': None}


def fake_core():
    """vendor 를 안 불러오고 Core 가 팀 로직에 무엇을 넘기는지만 봄"""
    calls = {}

    def reply(col, names, question, history=(), here=None, planner=None, nearest=None):
        calls['reply'] = (col, names, question, history, here, planner, nearest)
        return {'answer': 'a', 'language': 'English', 'action': None}, 'context'

    class Planner:
        def make(self, request, language=None, here=None):
            calls['make'] = (request, language, here)
            return {'answer': 'c', 'language': 'ภาษาไทย', 'course': {'minutes': 60, 'start': 's', 'stops': []}}

    core = Core.__new__(Core)
    core.col, planner = 'col', Planner()
    core._llm = (types.SimpleNamespace(reply=reply), 'names', planner)
    return core, planner, calls


def test_core_ask_passes_context_and_planner():
    core, planner, calls = fake_core()
    h = [{'question': 'q', 'answer': 'a'}]
    assert core.ask('거기는?', history=h, here='place:a', nearest='place:b')['language'] == 'en'
    assert calls['reply'] == ('col', 'names', '거기는?', h, 'place:a', planner, 'place:b')
    core.ask('강녕전')  # 안 보내면 history 는 빈 값, 위치는 None (planner 는 늘 넘겨서 코스 요청을 받음)
    assert calls['reply'] == ('col', 'names', '강녕전', (), None, planner, None)


def test_core_course_passes_start():
    core, _, calls = fake_core()
    assert core.course('40분', here='place:b')['language'] == 'th'
    assert calls['make'] == ('40분', None, 'place:b')
