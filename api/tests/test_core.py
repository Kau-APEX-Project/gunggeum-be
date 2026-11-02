"""팀 로직 언어 연결 (vendor 를 고치지 않고 language 요청 필드를 반영)"""
import threading
import types

from app.core import allow_forced_language, answer_in, to_code


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
