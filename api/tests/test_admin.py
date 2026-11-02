"""운영자 API (공지 · 해설 일정) + 개발용 테스트 페이지"""
from datetime import timedelta

import pytest

from app.settings import now

ADMIN = {'Authorization': 'Bearer test-admin', 'X-Admin-Name': 'yunseo'}


@pytest.fixture
def admin_on(monkeypatch):
    monkeypatch.setenv('ADMIN_TOKEN', 'test-admin')


def test_admin_off_without_token_setting(client, monkeypatch):
    monkeypatch.delenv('ADMIN_TOKEN', raising=False)
    r = client.get('/api/admin/notices', headers=ADMIN)
    assert r.status_code == 403 and r.json() == {'error': '관리자 기능이 꺼져 있습니다'}


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer nope'}, {'Authorization': 'test-admin'}])
def test_admin_needs_token(client, admin_on, headers):
    assert client.get('/api/admin/notices', headers=headers).status_code == 401
    assert client.post('/api/admin/tours', headers=headers, json={'date': now().date().isoformat(), 'times': ['10:00']}).status_code == 401


def test_guide_access_code_is_not_admin(client, admin_on, monkeypatch):
    monkeypatch.setenv('GUIDE_ACCESS_CODE', 'palace-2026')
    assert client.get('/api/admin/notices', headers={'Authorization': 'Bearer palace-2026'}).status_code == 401


def test_notice_with_manual_translation(client, admin_on, sql):
    r = client.post('/api/admin/notices', headers=ADMIN, json={
        'type': 'tour_cancelled', 'title': '오늘 14:00 영어 해설 우천 취소', 'body': '비로 취소됩니다',
        'translations': {'en': {'title': 'Today 14:00 English tour cancelled due to rain', 'body': 'Cancelled due to rain'}}})
    assert r.status_code == 201
    n = r.json()
    assert n['id'] == f"n-{now():%Y%m%d}-01" and n['createdBy'] == 'yunseo'
    assert set(n['translations']) == {'en'}

    # 관광객 쪽에 바로 보임: 영어는 번역, 태국어는 한국어 원문
    en = client.get('/api/notices', params={'lang': 'en'}).json()['notices'][0]
    th = client.get('/api/notices', params={'lang': 'th'}).json()['notices'][0]
    assert (en['title'], en['lang']) == ('Today 14:00 English tour cancelled due to rain', 'en')
    assert th['lang'] == 'ko'

    assert client.post('/api/admin/notices', headers=ADMIN, json={'type': 'weather', 'title': '폭염', 'body': '물'}).json()['id'] \
        == f"n-{now():%Y%m%d}-02"


def test_notice_auto_translate(client, admin_on):
    # 테스트 환경 번역기는 echo (한국어 그대로) → 영·태 둘 다 채워졌는지만 확인
    n = client.post('/api/admin/notices', headers=ADMIN, json={
        'type': 'weather', 'title': '폭염 주의', 'body': '물을 챙기세요', 'translate': True,
        'translations': {'en': {'title': 'Heat wave', 'body': 'Bring water'}}}).json()
    assert n['translations']['en'] == {'title': 'Heat wave', 'body': 'Bring water'}  # 직접 넣은 번역은 그대로
    assert n['translations']['th'] == {'title': '폭염 주의', 'body': '물을 챙기세요'}


def test_notice_duplicate_url_and_validation(client, admin_on):
    body = {'type': 'event_change', 'title': '야간 개장 변경', 'body': '...', 'url': 'https://example.test/notice/1'}
    assert client.post('/api/admin/notices', headers=ADMIN, json=body).status_code == 201
    assert client.post('/api/admin/notices', headers=ADMIN, json=body).status_code == 409
    assert client.post('/api/admin/notices', headers=ADMIN, json={**body, 'type': 'party', 'url': None}).status_code == 400
    assert client.post('/api/admin/notices', headers=ADMIN, json={**body, 'title': '', 'url': None}).status_code == 400
    assert client.post('/api/admin/notices', headers=ADMIN, json={**body, 'url': None, 'translations': {'fr': {'title': 'a', 'body': 'b'}}}).status_code == 400


def test_notice_list_and_delete(client, admin_on):
    nid = client.post('/api/admin/notices', headers=ADMIN, json={'type': 'weather', 'title': 't', 'body': 'b'}).json()['id']
    assert [x['id'] for x in client.get('/api/admin/notices', headers=ADMIN).json()['notices']] == [nid]
    assert client.delete(f'/api/admin/notices/{nid}', headers=ADMIN).status_code == 204
    assert client.delete(f'/api/admin/notices/{nid}', headers=ADMIN).status_code == 404
    assert client.get('/api/notices').json()['notices'] == []


def test_notice_id_after_delete(client, admin_on):
    # 01·02 중 01을 지운 뒤 넣어도 id 가 겹치지 않음 (예전엔 개수 + 1 = 02 → 500)
    add = lambda: client.post('/api/admin/notices', headers=ADMIN, json={'type': 'weather', 'title': 't', 'body': 'b'})
    first, _ = add().json()['id'], add()
    assert client.delete(f'/api/admin/notices/{first}', headers=ADMIN).status_code == 204
    r = add()
    assert r.status_code == 201 and r.json()['id'] == f"n-{now():%Y%m%d}-03"


def test_tours_add_list_delete(client, admin_on):
    today = now().date().isoformat()
    r = client.post('/api/admin/tours', headers=ADMIN, json={'date': today, 'times': ['14:00', '10:00', '14:00'], 'durationMin': 50})
    assert r.status_code == 201
    assert r.json()['tours'] == [
        {'time': '10:00', 'durationMin': 50, 'sessionCode': None, 'createdBy': 'yunseo'},
        {'time': '14:00', 'durationMin': 50, 'sessionCode': None, 'createdBy': 'yunseo'}]
    # 관광객 일정에 바로 반영
    assert [x['time'] for x in client.get('/api/tours/today').json()['tours']] == ['10:00', '14:00']

    # 같은 시각을 다시 넣으면 길이만 바뀜
    client.post('/api/admin/tours', headers=ADMIN, json={'date': today, 'times': ['10:00'], 'durationMin': 90})
    tours = client.get('/api/admin/tours', headers=ADMIN, params={'date': today}).json()['tours']
    assert [(x['time'], x['durationMin']) for x in tours] == [('10:00', 90), ('14:00', 50)]

    assert client.delete('/api/admin/tours', headers=ADMIN, params={'date': today, 'time': '10:00'}).status_code == 204
    assert client.delete('/api/admin/tours', headers=ADMIN, params={'date': today, 'time': '10:00'}).status_code == 404


@pytest.mark.parametrize('body', [
    {'times': ['10:00']},                                    # 날짜 없음
    {'date': 'tomorrow', 'times': ['10:00']},                # 날짜 형식
    {'date': 'TODAY', 'times': []},                          # 시각 없음
    {'date': 'TODAY', 'times': ['25:00']},                   # 없는 시각
    {'date': 'TODAY', 'times': ['9:00']},                    # HH:MM 아님
    {'date': 'TODAY', 'times': ['10:00'], 'durationMin': 5},  # 해설 길이 10분 미만
])
def test_tours_validation(client, admin_on, body):
    if body.get('date') == 'TODAY':
        body = {**body, 'date': now().date().isoformat()}
    assert client.post('/api/admin/tours', headers=ADMIN, json=body).status_code == 400


def test_tours_past_date_rejected(client, admin_on):
    past = (now().date() - timedelta(days=1)).isoformat()
    r = client.post('/api/admin/tours', headers=ADMIN, json={'date': past, 'times': ['10:00']})
    assert r.status_code == 400 and '지난 날짜' in r.json()['error']


def test_live_tester_only_with_dev_tools(client, monkeypatch):
    monkeypatch.delenv('DEV_TOOLS', raising=False)
    assert client.get('/api/dev/live-tester').status_code == 404
    monkeypatch.setenv('DEV_TOOLS', '1')
    r = client.get('/api/dev/live-tester')
    assert r.status_code == 200 and '라이브 투어 테스터' in r.text
