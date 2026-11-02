"""STT 벤치마크 v2 반영: 위치별 사전 · 후처리 사전 · 집 서버 Whisper 호출"""
import asyncio
import json

import httpx
import pytest

from app.live import postcorrect
from app.live.hints import Hints
from app.live.stt import WhisperHttpSTT, needs_postcorrect


def test_jamo_similarity_matches_report():
    # 보고서 3.5: 한 음절만 틀린 3음절 단어는 자모 단위로 0.92~0.93
    assert 0.9 < postcorrect.similarity('흑례문', '흥례문') < 0.95
    assert postcorrect.similarity('근정전', '근정전') == 1.0


@pytest.mark.parametrize('heard, fixed', [
    ('흑례문을 지나면', '흥례문을 지나면'),      # 보고서의 바로잡은 예 (조사는 그대로)
    ('신문문 쪽으로', '신무문 쪽으로'),
    ('경회로에서는', '경회루에서는'),
    ('건축문은 동쪽 문입니다', '건춘문은 동쪽 문입니다'),
    ('근정전 앞 월대', '근정전 앞 월대'),        # 이미 맞으면 그대로
])
def test_postcorrect_examples(heard, fixed):
    terms = ['흥례문', '신무문', '경회루', '건춘문', '근정전', '월대']
    assert postcorrect.correct(heard, terms) == fixed


def test_postcorrect_skips_one_syllable_and_unrelated():
    assert postcorrect.correct('칸 사이로 보세요', ['칸']) == '칸 사이로 보세요'
    assert postcorrect.correct('오늘 날씨가 좋습니다', ['근정전', '경회루']) == '오늘 날씨가 좋습니다'


def test_postcorrect_multi_word_term():
    assert postcorrect.correct('일월오봉도 병풍', ['일월오봉도 병풍']) == '일월오봉도 병풍'
    assert postcorrect.correct('일원오봉도 병풍이 있습니다', ['일월오봉도 병풍']) == '일월오봉도 병풍이 있습니다'


def test_needs_postcorrect(monkeypatch):
    monkeypatch.delenv('STT_POSTCORRECT', raising=False)
    monkeypatch.setenv('STT_PROVIDER', 'whisper_http')
    assert not needs_postcorrect()  # 받아쓰기 사전을 넣는 엔진에는 안 씀
    monkeypatch.setenv('STT_PROVIDER', 'transcribe')
    assert needs_postcorrect()
    monkeypatch.setenv('STT_POSTCORRECT', '0')
    assert not needs_postcorrect()


def test_hints_prompt(tmp_path, monkeypatch):
    path = tmp_path / 'hints.json'
    path.write_text(json.dumps({'_note': 'x', 'place:geunjeongjeon': ['근정전', '월대']}, ensure_ascii=False))
    monkeypatch.setenv('STT_HINTS_PATH', str(path))
    h = Hints.load()
    assert h.prompt('place:geunjeongjeon') == '경복궁 해설입니다. 근정전, 월대.'
    assert h.prompt(None) == '경복궁 해설입니다.' and h.terms('nowhere') == []
    monkeypatch.setenv('STT_HINTS_PATH', str(tmp_path / 'missing.json'))
    assert Hints.load().by_location == {}


def run(coro):
    return asyncio.run(coro)


def make_stt(monkeypatch, handler, urls='http://z6g4:9000,http://macmini:9000'):
    monkeypatch.setenv('STT_HTTP_URLS', urls)
    monkeypatch.setenv('STT_HTTP_TOKEN', 'secret')
    finals = []

    async def on_final(text):
        finals.append(text)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WhisperHttpSTT(on_final, Hints({'place:geunjeongjeon': ['근정전', '월대']}), client=client), finals


def test_whisper_sends_audio_prompt_and_token(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={'text': ' 이곳은 근정전입니다. ', 'seconds': 0.28})
    stt, finals = make_stt(monkeypatch, handler)
    run(stt.feed(b'RIFF....audio', 'place:geunjeongjeon'))
    assert finals == ['이곳은 근정전입니다.']
    req = seen[0]
    assert str(req.url) == 'http://z6g4:9000/transcribe' and req.headers['authorization'] == 'Bearer secret'
    body = req.content.decode('utf-8', 'replace')
    assert '경복궁 해설입니다. 근정전, 월대.' in body and 'RIFF....audio' in body


def test_whisper_falls_back_to_next_server(monkeypatch):
    def handler(req):
        if req.url.host == 'z6g4':
            raise httpx.ConnectError('down')
        return httpx.Response(200, json={'text': '경회루입니다'})
    stt, finals = make_stt(monkeypatch, handler)
    run(stt.feed(b'a', None))
    assert finals == ['경회루입니다']


def test_whisper_all_down_raises(monkeypatch):
    stt, finals = make_stt(monkeypatch, lambda req: httpx.Response(503))
    with pytest.raises(RuntimeError):
        run(stt.feed(b'a', None))
    assert finals == []


def test_whisper_ignores_empty_text_and_huge_audio(monkeypatch):
    stt, finals = make_stt(monkeypatch, lambda req: httpx.Response(200, json={'text': '  '}))
    run(stt.feed(b'a', None))
    assert finals == []
    with pytest.raises(ValueError):
        run(stt.feed(b'x' * 2_000_001, None))
