"""질문·카드·코스 API 계약 테스트 (API 명세서 v0.1). 실제 LLM·DB 대신 가짜 Core 를 끼워서 키 없이 돈다."""
import pytest
from fastapi.testclient import TestClient

from app.core import core_getter
from app.main import app


class FakeCore:
    def __init__(self):
        self.asked, self.requested = [], []
        self.context, self.course_here = [], []  # ask 의 (history, here, nearest) · course 의 출발 기준

    def ask(self, question, language=None, history=None, here=None, nearest=None):
        self.asked.append((question, language))
        self.context.append((history, here, nearest))
        if 'boom' in question:
            raise RuntimeError('OpenAI 키 없음 sk-secret')
        if '코스' in question:  # 팀 로직이 코스 요청으로 판정한 경우의 응답 모양 (llm-gps API.md §2)
            return {'answer': '왕비 이야기 코스입니다.', 'language': 'ko',
                    'action': {'type': 'course', 'course': {'minutes': 40, 'start': 'place:gyotaejeon',
                                                            'stops': [{'id': 'place:gyotaejeon', 'stayMin': 8}]}}}
        return {'answer': '[강녕전](card:b-163)은 왕의 침전입니다.', 'language': language or 'ko', 'action': None}

    def card(self, card_id):
        return {'id': card_id, 'type': 'building', 'name': '근정전'} if card_id == 'b-160' else None

    def course(self, request, language=None, here=None):
        self.requested.append((request, language))
        self.course_here.append(here)
        if 'one minute' in request:  # 시간 안에 다녀올 곳이 없으면 stops 가 빈 배열
            return {'answer': 'There is not enough time.', 'language': 'en',
                    'course': {'minutes': 1, 'start': 'place:gwanghwamun-gate', 'stops': []}}
        return {'answer': '...', 'language': 'en',
                'course': {'minutes': 30, 'start': 'place:gwanghwamun-gate',
                           'stops': [{'id': 'place:gyotaejeon', 'stayMin': 8}]}}


@pytest.fixture
def fake():
    core = FakeCore()
    app.dependency_overrides[core_getter] = lambda: (lambda: core)
    yield core
    app.dependency_overrides.clear()


@pytest.fixture
def client(fake):
    return TestClient(app, raise_server_exceptions=False)


def test_health_does_not_touch_core():
    # 의존성 교체 없이도 떠야 함 (키·DB 없어도 배포 확인 가능)
    r = TestClient(app).get('/api/health')
    assert r.status_code == 200 and r.json()['status'] == 'ok'  # API 명세서 6.1


def test_ask_ok(client, fake):
    r = client.post('/api/ask', json={'question': '  강녕전이 뭐야?  '})
    assert r.status_code == 200
    assert r.json() == {'answer': '[강녕전](card:b-163)은 왕의 침전입니다.', 'language': 'ko', 'action': None}
    assert fake.asked == [('강녕전이 뭐야?', None)]  # 앞뒤 공백 제거, 언어는 서버가 판정


def test_ask_language_field(client, fake):
    r = client.post('/api/ask', json={'question': '강녕전이 뭐야?', 'language': 'th'})
    assert r.status_code == 200 and fake.asked == [('강녕전이 뭐야?', 'th')]
    assert client.post('/api/ask', json={'question': 'hi', 'language': 'English'}).status_code == 400


def test_ask_context_fields_pass_through(client, fake):
    history = [{'question': '경회루가 뭐야?', 'answer': '[경회루](card:b-170)는 연회 장소입니다.'}]
    r = client.post('/api/ask', json={'question': '거기는 누가 썼어?', 'history': history,
                                      'here': 'place:gyeonghoeru', 'nearest': 'place:gyeonghoeru'})
    assert r.status_code == 200
    assert fake.context == [(history, 'place:gyeonghoeru', 'place:gyeonghoeru')]


def test_ask_without_context_fields_is_same_as_before(client, fake):
    client.post('/api/ask', json={'question': '강녕전이 뭐야?'})
    assert fake.context == [(None, None, None)]


def test_ask_odd_context_values_are_not_400(client, fake):
    # 형식 검사는 팀 로직(ask.reply)이 함: 틀린 history 항목은 버리고, 모르는 here 는 무시 → BE 는 거절하지 않고 그대로 넘김
    r = client.post('/api/ask', json={'question': '여기 뭐야?', 'history': 'oops', 'here': 123, 'nearest': ['x']})
    assert r.status_code == 200 and fake.context == [('oops', 123, ['x'])]


def test_ask_course_action_passes_through(client):
    r = client.post('/api/ask', json={'question': '40분 코스 짜줘'})
    assert r.status_code == 200
    action = r.json()['action']
    assert action['type'] == 'course' and action['course']['start'] == 'place:gyotaejeon'
    assert action['course']['stops'] == [{'id': 'place:gyotaejeon', 'stayMin': 8}]


def test_ask_over_300_chars_is_400(client, fake):
    assert client.post('/api/ask', json={'question': '가' * 300}).status_code == 200
    assert client.post('/api/ask', json={'question': '가' * 301}).status_code == 400  # API 명세서 1.3


@pytest.mark.parametrize('body', [{}, {'question': ''}, {'question': '   '}, {'question': 3}, {'q': 'hi'}])
def test_ask_bad_body_is_400(client, body):
    r = client.post('/api/ask', json=body)
    assert r.status_code == 400 and 'error' in r.json()


def test_ask_not_json_is_400(client):
    r = client.post('/api/ask', content='question=hi', headers={'Content-Type': 'application/json'})
    assert r.status_code == 400 and 'error' in r.json()


def test_server_error_hides_details(client):
    r = client.post('/api/ask', json={'question': 'boom'})
    assert r.status_code == 500
    assert r.json() == {'error': '답변을 만들지 못했습니다'}  # 키·예외 문구가 새지 않음


def test_card_ok_and_cached(client):
    r = client.get('/api/card', params={'id': 'b-160'})
    assert r.status_code == 200 and r.json()['name'] == '근정전'
    assert 'max-age=86400' in r.headers['cache-control']


def test_card_missing_id_is_400(client):
    r = client.get('/api/card')
    assert r.status_code == 400 and 'error' in r.json()


def test_card_unknown_is_404(client):
    r = client.get('/api/card', params={'id': 'x-1'})
    assert r.status_code == 404 and r.json() == {'error': '없는 카드'}


def test_course_ok(client, fake):
    r = client.post('/api/course', json={'request': 'a quiet 30-minute walk'})
    assert r.status_code == 200
    assert r.json()['course']['stops'][0] == {'id': 'place:gyotaejeon', 'stayMin': 8}
    assert fake.requested == [('a quiet 30-minute walk', None)]
    assert r.json()['language'] == 'en'
    assert r.json()['course']['start'] == 'place:gwanghwamun-gate'
    assert fake.course_here == [None]  # 위치를 안 보내면 지금과 같이 (팀 로직이 광화문 출발)


def test_course_start_uses_nearest_then_here(client, fake):
    client.post('/api/course', json={'request': '40분', 'nearest': 'place:gyotaejeon', 'here': 'place:geunjeongjeon'})
    client.post('/api/course', json={'request': '40분', 'here': 'place:geunjeongjeon'})
    client.post('/api/course', json={'request': '40분', 'nearest': None})
    assert fake.course_here == ['place:gyotaejeon', 'place:geunjeongjeon', None]


def test_course_empty_stops_passes_through(client):
    r = client.post('/api/course', json={'request': 'one minute tour'})
    assert r.status_code == 200 and r.json()['course']['stops'] == [] and r.json()['answer']


def test_course_empty_is_400(client):
    assert client.post('/api/course', json={'request': ''}).status_code == 400


def test_bad_body_is_400_even_if_core_cannot_start():
    # 키·DB 가 없어 Core 를 못 만드는 상황에서도 잘못된 요청은 400 이어야 함
    def broken():
        raise RuntimeError('no key')
    app.dependency_overrides[core_getter] = lambda: broken
    try:
        c = TestClient(app, raise_server_exceptions=False)
        assert c.post('/api/ask', json={'question': ''}).status_code == 400
        assert c.get('/api/card').status_code == 400
        assert c.post('/api/ask', json={'question': 'hi'}).status_code == 500
    finally:
        app.dependency_overrides.clear()


def test_unknown_path_is_404(client):
    r = client.get('/api/nope')
    assert r.status_code == 404 and r.json() == {'error': '없는 경로'}
