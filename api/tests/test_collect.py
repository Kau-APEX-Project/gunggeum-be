"""공지 자동 수집 → 초안 → 운영자 승인"""
from datetime import timedelta

import httpx
import pytest

from app import collect
from app.settings import now

ADMIN = {'Authorization': 'Bearer test-admin', 'X-Admin-Name': 'yunseo'}
TODAY = now().date()
ROBOTS = 'User-agent: *\nDisallow: /_mngr_/\nDisallow: /search/\nDisallow: /bbs/\nAllow: /\n'


def row(nid, title, day, palace='gbg', extra=''):
    return (f'<tr><td class="m_none">1</td><td class="{palace}"><span class="color bold">궁</span></td>'
            f'<td class="tit"> <a href="#;" class="ellipsis txt_line1" onclick="fn_goView(\'{nid}\'{extra})" title="t">\n {title}</a></td>'
            f'<td class="info first">\n {day}</td><td class="m_none">409</td></tr>')


def page(*rows):
    # 실제 페이지처럼 표 밖 스크립트에도 fn_goView 가 있음
    return '<script>function fn_goView(id, notice) { }</script><table><tbody>' + ''.join(rows) + '</tbody></table>'


def web(body='', status=200, robots=ROBOTS, robots_status=200, seen=None):
    def handler(req):
        if seen is not None:
            seen.append(str(req.url))
        return httpx.Response(robots_status, text=robots) if req.url.path == '/robots.txt' else httpx.Response(status, text=body)
    return httpx.Client(transport=httpx.MockTransport(handler), headers={'User-Agent': collect.AGENT})


A, B = '20261123010101000001', '20261123010101000002'


@pytest.fixture
def admin_on(monkeypatch):
    monkeypatch.setenv('ADMIN_TOKEN', 'test-admin')


@pytest.fixture
def drafts(client, sql, admin_on):
    """A·B 두 건이 초안으로 들어온 상태"""
    collect.run(sql, web(page(row(A, '영어 해설 일시 중단', TODAY), row(B, '개방 시간 조정', TODAY))))
    return client


def approve_body(**kw):
    return {'type': 'tour_cancelled', 'title': '영어 해설 쉼', 'body': '오늘 영어 해설은 없습니다.',
            'en': {'title': 'No English tour', 'body': 'No English tour today.'},
            'th': {'title': 'ไม่มีทัวร์', 'body': 'วันนี้ไม่มีทัวร์'}, **kw}


# ---------- 목록 읽기 ----------

def test_parse_list():
    got = collect.parse(page(row(A, '10~11월 &quot;관람&quot; <b>안내</b>', '2026-11-03'),
                             row(B, '석조전 음악회', '2026-11-04', palace='dsg'),        # 덕수궁은 버림
                             row('20261101010101000003', '고정 공지', '2026-11-01', extra=", 'Y'")))
    assert [(x['title'], x['date'].isoformat()) for x in got] == [('10~11월 "관람" 안내', '2026-11-03'), ('고정 공지', '2026-11-01')]
    assert got[0]['url'] == f'{collect.PAGE}?schM=view&id={A}&schBcid=notice01'


def test_parse_same_notice_twice():
    assert len(collect.parse(page(row(A, 'a', '2026-11-03'), row(A, 'a', '2026-11-03')))) == 1


def test_fetch_reads_robots_then_one_list_page():
    seen = []
    assert len(collect.fetch(web(page(row(A, 'a', TODAY)), seen=seen))) == 1
    assert seen == [f'{collect.SITE}/robots.txt', collect.LIST_URL]


@pytest.mark.parametrize('kw', [
    {'body': '<html>점검 중</html>'},                          # 목록 모양이 바뀜
    {'body': 'x', 'status': 503},
    {'body': page(row(A, 'a', TODAY)), 'robots': 'User-agent: *\nDisallow: /ROYAL/\n'},
    {'body': page(row(A, 'a', TODAY)), 'robots_status': 500},
])
def test_fetch_errors(kw):
    with pytest.raises(collect.CollectError):
        collect.fetch(web(**kw))


def test_fetch_connection_error():
    def boom(req):
        raise httpx.ConnectError('no')
    with pytest.raises(collect.CollectError):
        collect.fetch(httpx.Client(transport=httpx.MockTransport(boom)))


# ---------- 저장 ----------

def test_collect_only_new_and_recent(client, sql):
    old = TODAY - timedelta(days=collect.MAX_AGE_DAYS + 1)
    body = page(row(A, 'a', TODAY), row(B, 'old', old))
    assert [x['id'] for x in collect.run(sql, web(body))] == [A]
    assert collect.run(sql, web(body)) == []  # 다시 수집해도 중복 없음
    assert client.get('/api/notices').json()['notices'] == []  # 승인 전에는 관람객에게 안 보임


def test_collect_skips_url_already_published(client, sql, admin_on):
    url = f'{collect.PAGE}?schM=view&id={A}&schBcid=notice01'
    assert client.post('/api/admin/notices', headers=ADMIN, json={'type': 'weather', 'title': 't', 'body': 'b', 'url': url}).status_code == 201
    assert collect.run(sql, web(page(row(A, 'a', TODAY)))) == []


def test_collect_failure_is_recorded_and_cleared(client, sql, admin_on):
    with pytest.raises(collect.CollectError):
        collect.run(sql, web('x', status=503))
    st = client.get('/api/admin/notice-drafts', headers=ADMIN).json()['collect']
    assert st['lastOkAt'] is None and '503' in st['lastError'] and st['lastErrorAt']
    collect.run(sql, web(page(row(A, 'a', TODAY))))
    st = client.get('/api/admin/notice-drafts', headers=ADMIN).json()['collect']
    assert st['lastOkAt'] and st['lastError'] is None


def test_notify_only_with_topic_and_new(monkeypatch):
    import boto3
    sent = []
    monkeypatch.setattr(boto3, 'client', lambda *a, **k: type('S', (), {'publish': lambda self, **kw: sent.append(kw)})())
    new = [{'id': A, 'title': '해설 중단', 'date': TODAY, 'url': 'https://example.test/1'}]
    monkeypatch.delenv('NOTICE_SNS_TOPIC_ARN', raising=False)
    collect.notify(new)
    assert sent == []
    monkeypatch.setenv('NOTICE_SNS_TOPIC_ARN', 'arn:aws:sns:x:1:t')
    collect.notify([])
    assert sent == []
    collect.notify(new)
    assert sent[0]['TopicArn'] == 'arn:aws:sns:x:1:t' and '해설 중단' in sent[0]['Message'] and sent[0]['Subject'].isascii()


def test_notify_failure_keeps_drafts(client, sql, admin_on, monkeypatch):
    import boto3

    def boom(*a, **k):
        raise RuntimeError('no permission')
    monkeypatch.setattr(boto3, 'client', boom)
    monkeypatch.setenv('NOTICE_SNS_TOPIC_ARN', 'arn:aws:sns:x:1:t')
    assert len(collect.run(sql, web(page(row(A, 'a', TODAY))))) == 1
    assert len(client.get('/api/admin/notice-drafts', headers=ADMIN).json()['drafts']) == 1


# ---------- 승인 · 거절 ----------

@pytest.mark.parametrize('method,path', [('get', ''), ('post', f'/{A}/preview'), ('post', f'/{A}/approve'), ('post', f'/{A}/reject')])
def test_drafts_need_admin_token(drafts, method, path):
    kw = {} if method == 'get' else {'json': approve_body()}
    assert getattr(drafts, method)('/api/admin/notice-drafts' + path, **kw).status_code == 401


def test_list_drafts(drafts):
    got = drafts.get('/api/admin/notice-drafts', headers=ADMIN).json()['drafts']
    assert {x['id'] for x in got} == {A, B}
    assert all(x['status'] == 'pending' and x['noticeId'] is None and x['date'] == TODAY.isoformat() for x in got)
    assert drafts.get('/api/admin/notice-drafts', headers=ADMIN, params={'status': 'x'}).status_code == 400


def test_preview_does_not_publish(drafts):
    r = drafts.post(f'/api/admin/notice-drafts/{A}/preview', headers=ADMIN, json={'title': '제목', 'body': '요약'})
    assert r.status_code == 200 and r.json() == {k: {'title': '제목', 'body': '요약'} for k in ('en', 'th')}  # 테스트 번역기는 echo
    assert drafts.get('/api/notices').json()['notices'] == []
    assert drafts.post('/api/admin/notice-drafts/0/preview', headers=ADMIN, json={'title': 'a', 'body': 'b'}).status_code == 404


def test_approve_publishes_with_source(drafts):
    r = drafts.post(f'/api/admin/notice-drafts/{A}/approve', headers=ADMIN, json=approve_body())
    assert r.status_code == 201 and r.json()['createdBy'] == 'yunseo'
    for lang, title in (('en', 'No English tour'), ('th', 'ไม่มีทัวร์'), ('ko', '영어 해설 쉼')):
        n = drafts.get('/api/notices', params={'lang': lang}).json()['notices']
        assert len(n) == 1 and n[0]['title'] == title and n[0]['lang'] == lang
        assert n[0]['sourceUrl'] == f'{collect.PAGE}?schM=view&id={A}&schBcid=notice01'
    done = drafts.get('/api/admin/notice-drafts', headers=ADMIN, params={'status': 'approved'}).json()['drafts']
    assert [(x['id'], x['noticeId'], x['decidedBy']) for x in done] == [(A, r.json()['id'], 'yunseo')]
    assert [x['id'] for x in drafts.get('/api/admin/notice-drafts', headers=ADMIN).json()['drafts']] == [B]


def test_decide_only_once(drafts):
    assert drafts.post(f'/api/admin/notice-drafts/{A}/approve', headers=ADMIN, json=approve_body()).status_code == 201
    assert drafts.post(f'/api/admin/notice-drafts/{A}/approve', headers=ADMIN, json=approve_body()).status_code == 409
    assert drafts.post(f'/api/admin/notice-drafts/{A}/reject', headers=ADMIN).status_code == 409
    assert drafts.post('/api/admin/notice-drafts/0/reject', headers=ADMIN).status_code == 404
    assert len(drafts.get('/api/notices').json()['notices']) == 1


@pytest.mark.parametrize('drop', ['en', 'th', 'type', 'title', 'body'])
def test_approve_needs_everything(drafts, drop):
    body = approve_body()
    del body[drop]
    assert drafts.post(f'/api/admin/notice-drafts/{A}/approve', headers=ADMIN, json=body).status_code == 400
    assert drafts.get('/api/notices').json()['notices'] == []


def test_approve_rolls_back_when_url_published_by_hand(drafts, sql):
    url = f'{collect.PAGE}?schM=view&id={A}&schBcid=notice01'
    drafts.post('/api/admin/notices', headers=ADMIN, json={'type': 'weather', 'title': 't', 'body': 'b', 'url': url})
    assert drafts.post(f'/api/admin/notice-drafts/{A}/approve', headers=ADMIN, json=approve_body()).status_code == 409
    assert sql.execute('select status from notice_draft where id = %s', (A,)).fetchone()['status'] == 'pending'


def test_reject_then_collect_again_stays_rejected(drafts, sql):
    r = drafts.post(f'/api/admin/notice-drafts/{B}/reject', headers=ADMIN)
    assert r.status_code == 200 and r.json()['status'] == 'rejected' and r.json()['decidedBy'] == 'yunseo'
    assert collect.run(sql, web(page(row(B, '개방 시간 조정', TODAY)))) == []
    assert drafts.get('/api/notices').json()['notices'] == []


def test_delete_notice_keeps_draft_decided(drafts, sql):
    nid = drafts.post(f'/api/admin/notice-drafts/{A}/approve', headers=ADMIN, json=approve_body()).json()['id']
    assert drafts.delete(f'/api/admin/notices/{nid}', headers=ADMIN).status_code == 204
    assert collect.run(sql, web(page(row(A, 'a', TODAY)))) == []  # 지운 공지가 다시 초안으로 안 들어옴


# ---------- 명령 ----------

def test_cli_collect(pg_url, client, monkeypatch, capsys):
    from app import cli
    monkeypatch.setenv('DATABASE_URL', pg_url)
    monkeypatch.setattr(collect, 'fetch', lambda client=None: collect.parse(page(row(A, '해설 중단', TODAY))))
    cli.main(['collect'])
    assert '새 초안 1건' in capsys.readouterr().out

    def boom(client=None):
        raise collect.CollectError('막힘')
    monkeypatch.setattr(collect, 'fetch', boom)
    with pytest.raises(SystemExit) as e:
        cli.main(['collect'])
    assert '막힘' in str(e.value)
