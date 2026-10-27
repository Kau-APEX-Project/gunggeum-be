"""라이브 투어: 세션 REST (API 명세서 7.2~7.5) + WebSocket (7.6)"""
import re

import pytest
from starlette.websockets import WebSocketDisconnect


def create(client, **body):
    r = client.post('/api/sessions', json={'consent': True, 'title': '경복궁 정기 해설', 'guideName': 'Guide Kim', **body})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_needs_consent(client):
    r = client.post('/api/sessions', json={'consent': False})
    assert r.status_code == 400 and 'consent' in r.json()['error']
    assert client.post('/api/sessions', json={}).status_code == 400


def test_create_checks_access_code(client, monkeypatch):
    monkeypatch.setenv('GUIDE_ACCESS_CODE', 'palace-2026')
    assert client.post('/api/sessions', json={'consent': True}).status_code == 403
    assert client.post('/api/sessions', json={'consent': True, 'accessCode': 'wrong'}).status_code == 403
    assert client.post('/api/sessions', json={'consent': True, 'accessCode': 'palace-2026'}).status_code == 201


def test_create_and_info(client, sql):
    s = create(client)
    assert re.fullmatch(r'GB-\d{4}', s['code'])
    assert s['joinUrl'] == f"https://example.test/live/{s['code']}"
    assert s['sourceLang'] == 'ko' and len(s['guideToken']) > 30 and s['startedAt'].endswith('+09:00')
    # 토큰 원문은 DB 에 없음
    row = sql.execute('select guide_token_hash from live_session where code = %s', (s['code'],)).fetchone()
    assert row['guide_token_hash'] != s['guideToken']

    info = client.get(f"/api/sessions/{s['code']}").json()
    assert info == {'code': s['code'], 'title': '경복궁 정기 해설', 'guideName': 'Guide Kim', 'status': 'waiting',
                    'startedAt': s['startedAt'], 'micOn': False}


@pytest.mark.parametrize('code', ['GB-0000', 'gb-1234', 'abc', 'GB-12345'])
def test_unknown_session_is_404(client, code):
    assert client.get(f'/api/sessions/{code}').status_code == 404
    assert client.get(f'/api/sessions/{code}/summary').status_code == 404


def test_end_needs_guide_token(client):
    s = create(client)
    url = f"/api/sessions/{s['code']}/end"
    assert client.post(url).status_code == 401
    assert client.post(url, headers={'Authorization': 'Bearer nope'}).status_code == 401
    r = client.post(url, headers={'Authorization': f"Bearer {s['guideToken']}"})
    assert r.status_code == 200 and r.json()['code'] == s['code']
    assert client.get(f"/api/sessions/{s['code']}").json()['status'] == 'ended'
    # 두 번 끝내도 같은 요약
    assert client.post(url, headers={'Authorization': f"Bearer {s['guideToken']}"}).json() == r.json()


def test_live_flow(client):
    s = create(client)
    code, token = s['code'], s['guideToken']
    with client.websocket_connect(f'/ws/sessions/{code}/guide?token={token}') as g:
        assert g.receive_json() == {'type': 'presence', 'participants': 0, 'languages': {}}
        assert client.get(f'/api/sessions/{code}').json()['status'] == 'live'

        with client.websocket_connect(f'/ws/sessions/{code}/listen?lang=en') as en, \
                client.websocket_connect(f'/ws/sessions/{code}/listen?lang=th') as th:
            assert en.receive_json() == {'type': 'mic', 'on': False}
            assert th.receive_json() == {'type': 'mic', 'on': False}
            assert g.receive_json()['participants'] == 1
            assert g.receive_json() == {'type': 'presence', 'participants': 2, 'languages': {'en': 1, 'th': 1}}

            # 마이크 켜기 → 관람객 모두에게
            g.send_json({'type': 'mic', 'on': True})
            assert en.receive_json() == {'type': 'mic', 'on': True}
            assert th.receive_json() == {'type': 'mic', 'on': True}
            assert g.receive_json() == {'type': 'mic', 'on': True}
            assert client.get(f'/api/sessions/{code}').json()['micOn'] is True

            # 해설 문장 → 해설사 미리보기 + 언어별 자막 (번역은 echo)
            g.send_json({'type': 'text', 'textKo': '이곳은 근정전입니다.'})
            assert g.receive_json() == {'type': 'transcript', 'seq': 1, 'textKo': '이곳은 근정전입니다.'}
            sub = en.receive_json()
            assert sub['type'] == 'subtitle' and sub['seq'] == 1 and sub['lang'] == 'en'
            assert sub['textKo'] == '이곳은 근정전입니다.' and '(card:b-160)' in sub['text'] and sub['cardIds'] == ['b-160']
            assert th.receive_json()['lang'] == 'th'

            # 재연결: 놓친 순번 알림, ping
            en.send_json({'type': 'resume', 'lastSeq': 0})
            assert en.receive_json() == {'type': 'gap', 'fromSeq': 1, 'toSeq': 1}
            en.send_json({'type': 'resume', 'lastSeq': 1})  # 놓친 것 없음 → 응답 없음, 다음 ping 이 바로 옴
            en.send_json({'type': 'ping'})
            assert en.receive_json() == {'type': 'pong'}

            live = client.get(f'/api/sessions/{code}/summary').json()
            assert live['peakParticipants'] == 2 and live['languages'] == {'en': 1, 'th': 1}
            assert live['mentionedCards'] == ['b-160']

            # 종료 → 모두에게 session_ended
            ended = client.post(f'/api/sessions/{code}/end', headers={'Authorization': f'Bearer {token}'}).json()
            assert en.receive_json() == {'type': 'session_ended'}
            assert th.receive_json() == {'type': 'session_ended'}
            assert g.receive_json() == {'type': 'session_ended'}

    # 종료 후 요약은 DB 에서 (Redis 진행 상태는 지워짐)
    assert ended == {**live, 'durationSec': ended['durationSec']}
    assert client.get(f'/api/sessions/{code}/summary').json() == ended


def close_code(client, url):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(url) as ws:
            ws.receive_json()
    return e.value.code


def test_ws_rejections(client):
    s = create(client)
    code = s['code']
    assert close_code(client, '/ws/sessions/GB-0000/listen') == 4404
    assert close_code(client, f'/ws/sessions/{code}/listen?lang=fr') == 4400
    assert close_code(client, f'/ws/sessions/{code}/guide') == 4401
    assert close_code(client, f'/ws/sessions/{code}/guide?token=wrong') == 4401
    client.post(f'/api/sessions/{code}/end', headers={'Authorization': f"Bearer {s['guideToken']}"})
    assert close_code(client, f"/ws/sessions/{code}/guide?token={s['guideToken']}") == 4410


def test_listener_joining_ended_session_gets_ended(client):
    s = create(client)
    client.post(f"/api/sessions/{s['code']}/end", headers={'Authorization': f"Bearer {s['guideToken']}"})
    with client.websocket_connect(f"/ws/sessions/{s['code']}/listen?lang=en") as ws:
        assert ws.receive_json() == {'type': 'session_ended'}


def test_guide_disconnect_turns_mic_off(client):
    s = create(client)
    code = s['code']
    with client.websocket_connect(f'/ws/sessions/{code}/listen?lang=en') as en:
        assert en.receive_json() == {'type': 'mic', 'on': False}
        with client.websocket_connect(f"/ws/sessions/{code}/guide?token={s['guideToken']}") as g:
            g.receive_json()
            g.send_json({'type': 'mic', 'on': True})
            assert en.receive_json() == {'type': 'mic', 'on': True}
            g.receive_json()
        assert en.receive_json() == {'type': 'mic', 'on': False}  # S-04


def test_location_drives_stt_hints_and_postcorrect(client, monkeypatch):
    """STT 벤치마크 v2: 해설사가 알려 준 위치의 사전으로 받아쓰고(Whisper prompt), 약한 엔진이면 후처리로 바로잡음"""
    from app.live.hints import Hints
    from app.live.stt import WhisperHttpSTT

    client.app.state.pipeline.hints = Hints({'place:heungnyemun': ['흥례문', '영제교']})
    prompts = []

    async def fake_transcribe(self, audio, prompt):
        prompts.append((audio, prompt))
        return '흑례문을 지나면 영제교가 있습니다'
    monkeypatch.setattr(WhisperHttpSTT, 'transcribe', fake_transcribe)
    monkeypatch.setenv('STT_PROVIDER', 'whisper_http')
    monkeypatch.setenv('STT_POSTCORRECT', '1')  # 여기서는 후처리까지 켜서 확인

    s = create(client)
    code = s['code']
    with client.websocket_connect(f"/ws/sessions/{code}/guide?token={s['guideToken']}") as g, \
            client.websocket_connect(f'/ws/sessions/{code}/listen?lang=en') as en:
        assert en.receive_json()['type'] == 'mic'
        g.send_json({'type': 'location', 'poiId': 'place:heungnyemun'})
        g.send_bytes(b'utterance-1')  # 발화 하나 = 프레임 하나
        sub = en.receive_json()
        assert sub['type'] == 'subtitle' and sub['textKo'] == '흥례문을 지나면 영제교가 있습니다'
    assert prompts == [(b'utterance-1', '경복궁 해설입니다. 흥례문, 영제교.')]


def test_stt_failure_tells_guide_once(client, monkeypatch):
    from app.live.stt import WhisperHttpSTT

    async def down(self, audio, prompt):
        raise RuntimeError('모든 STT 서버 실패')
    monkeypatch.setattr(WhisperHttpSTT, 'transcribe', down)
    monkeypatch.setenv('STT_PROVIDER', 'whisper_http')
    s = create(client)
    with client.websocket_connect(f"/ws/sessions/{s['code']}/guide?token={s['guideToken']}") as g:
        assert g.receive_json()['type'] == 'presence'
        g.send_bytes(b'a')
        g.send_bytes(b'b')
        g.send_json({'type': 'ping'})
        assert g.receive_json() == {'type': 'error', 'message': '음성 인식 연결에 실패했습니다'}
        assert g.receive_json() == {'type': 'pong'}  # 같은 오류를 두 번 보내지 않음
