"""해설 일정 · 공지 · 방문 집계 (API 명세서 6.2 · 6.3 · 7.1) + 운영자 CLI"""
from datetime import timedelta

from app import cli
from app.settings import now


def test_tours_today(client, sql):
    today = now().date()
    sql.execute("insert into tour_schedule (tour_date, start_time, duration_min) values "
                "(%s, '00:00', 1), (%s, '23:59', 60), (%s, '12:00', 60), (%s, '10:00', 60)",
                (today, today, today, today - timedelta(days=1)))
    s = client.post('/api/sessions', json={'consent': True, 'tourTime': '12:00'}).json()
    sql.execute("update live_session set status = 'live' where code = %s", (s['code'],))

    r = client.get('/api/tours/today').json()
    assert r['date'] == today.isoformat()
    assert r['tours'] == [  # 어제 일정은 빠짐
        {'time': '00:00', 'status': 'ended', 'sessionCode': None},
        {'time': '12:00', 'status': 'live', 'sessionCode': s['code']},
        {'time': '23:59', 'status': 'upcoming', 'sessionCode': None},
    ]


def test_notices(client, sql):
    t = now()
    sql.execute("insert into notice (id, type, title, body, published_at) values "
                "('n-1', 'tour_cancelled', '14:00 영어 해설 취소', '우천', %s), ('n-2', 'weather', '폭염 주의', '물', %s)",
                (t - timedelta(hours=2), t - timedelta(hours=1)))
    sql.execute("insert into notice_translation values ('n-1', 'en', 'Today 14:00 English tour cancelled due to rain', 'Rain')")

    en = client.get('/api/notices', params={'lang': 'en'}).json()['notices']
    assert [(x['id'], x['lang']) for x in en] == [('n-2', 'ko'), ('n-1', 'en')]  # 최신순, 번역 없으면 원문
    assert en[1]['title'] == 'Today 14:00 English tour cancelled due to rain' and en[1]['type'] == 'tour_cancelled'
    assert en[1]['publishedAt'].endswith('+09:00')

    since = (t - timedelta(minutes=90)).isoformat()
    assert [x['id'] for x in client.get('/api/notices', params={'since': since}).json()['notices']] == ['n-2']
    assert client.get('/api/notices', params={'lang': 'fr'}).status_code == 400


def test_visit_stats(client, sql):
    body = {'poiId': 'place:geunjeongjeon', 'event': 'stamp', 'lang': 'en', 'date': now().date().isoformat()}
    assert client.post('/api/stats/visits', json=body).status_code == 204
    assert client.post('/api/stats/visits', json=body).status_code == 204
    assert sql.execute('select count from visit_stat').fetchone()['count'] == 2

    assert client.post('/api/stats/visits', json={**body, 'event': 'enter'}).status_code == 400
    assert client.post('/api/stats/visits', json={**body, 'poiId': 'a b'}).status_code == 400
    old = (now().date() - timedelta(days=5)).isoformat()
    assert client.post('/api/stats/visits', json={**body, 'date': old}).status_code == 400


def test_cli(client, capsys):
    day = now().date().isoformat()
    cli.main(['tours', 'add', day, '10:00', '14:00'])
    assert '10:00  60분' in capsys.readouterr().out
    assert [x['time'] for x in client.get('/api/tours/today').json()['tours']] == ['10:00', '14:00']

    cli.main(['notices', 'add', '--type', 'weather', '--title', '폭염', '--body', '물 챙기세요',
              '--en-title', 'Heat wave', '--en-body', 'Bring water'])
    assert '추가: n-' in capsys.readouterr().out
    n = client.get('/api/notices', params={'lang': 'en'}).json()['notices'][0]
    assert (n['title'], n['lang']) == ('Heat wave', 'en')
