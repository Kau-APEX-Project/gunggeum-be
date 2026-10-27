"""질문·카드·코스 API 계약 테스트 (API 명세서 v0.1). 실제 LLM·DB 대신 가짜 Core 를 끼워서 키 없이 돈다."""
import pytest
from fastapi.testclient import TestClient

from app.core import core_getter
from app.main import app


class FakeCore:
    def __init__(self):
        self.asked, self.requested = [], []

    def ask(self, question, language=None):
        self.asked.append((question, language))
        if 'boom' in question:
            raise RuntimeError('OpenAI 키 없음 sk-secret')
        return {'answer': '[강녕전](card:b-163)은 왕의 침전입니다.', 'language': language or 'ko', 'action': None}

    def card(self, card_id):
        return {'id': card_id, 'type': 'building', 'name': '근정전'} if card_id == 'b-160' else None

    def course(self, request, language=None):
        self.requested.append((request, language))
        return {'answer': '...', 'language': 'en',
                'course': {'minutes': 30, 'stops': [{'id': 'place:gyotaejeon', 'stayMin': 8}]}}


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
