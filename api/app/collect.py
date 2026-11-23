"""공지 자동 수집: 궁능유적본부의 경복궁 공지 목록에서 새 공지의 제목·날짜·링크만 초안(notice_draft)으로 저장.

  docker compose exec -T api python -m app.cli collect      (서버는 systemd 타이머가 1시간마다: deploy/app/README.md)

관람객에게 바로 나가지 않음. 운영자가 /api/admin/notice-drafts 에서 요약·번역을 확인하고 승인한 것만 공지가 됨.
본문은 가져오지 않음: 이미지뿐인 공지가 있고, 공공누리 표시가 없는 글을 옮기지 않기 위해서. 운영자가 링크로 확인함."""
import html
import logging
import re
import urllib.robotparser
from datetime import date, timedelta

import httpx

from app.settings import env, now

log = logging.getLogger('gunggeum.collect')

SITE = 'https://royal.khs.go.kr'
PAGE = f'{SITE}/ROYAL/contents/R403000000.do'
LIST_URL = f'{PAGE}?schGroupCode=gbg'  # gbg = 경복궁
AGENT = 'notice-collector'
MAX_AGE_DAYS = 14  # 처음 켤 때 오래된 공지가 한꺼번에 들어오지 않게

ROW = re.compile(r'<tr\b.*?</tr>', re.S)
VIEW = re.compile(r"""fn_goView\(\s*'(\d{10,30})'[^)]*\)[^>]*>(.*?)</a>""", re.S)
DAY = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
GBG = re.compile(r"""<td\s+class="gbg\b""")


class CollectError(Exception):
    """사이트가 막혔거나 목록 모양이 바뀜"""


def parse(page: str) -> list[dict]:
    """목록 HTML → [{id, title, date, url}]. 경복궁 줄만"""
    out = {}
    for row in ROW.findall(page):
        m, d = VIEW.search(row), DAY.search(row)
        if not (m and d and GBG.search(row)):
            continue
        title = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', m.group(2)))).strip()
        if title:
            out[m.group(1)] = {'id': m.group(1), 'title': title[:200], 'date': date(*map(int, d.groups())),
                               'url': f'{PAGE}?schM=view&id={m.group(1)}&schBcid=notice01'}
    return list(out.values())


def fetch(client: httpx.Client | None = None) -> list[dict]:
    with client or httpx.Client(timeout=20, follow_redirects=True, headers={'User-Agent': AGENT}) as c:
        try:
            r = c.get(f'{SITE}/robots.txt')
            robots = urllib.robotparser.RobotFileParser()
            if r.status_code == 200:
                robots.parse(r.text.splitlines())
            elif r.status_code == 404:
                robots.allow_all = True
            else:
                raise CollectError(f'robots.txt {r.status_code}')
            robots.modified()
            if not robots.can_fetch(AGENT, LIST_URL):
                raise CollectError('robots.txt 가 공지 목록을 막음')
            r = c.get(LIST_URL)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise CollectError(f'사이트 접속 실패: {e!r}') from e
    rows = parse(r.text)
    if not rows:
        raise CollectError('공지 목록을 읽지 못함 (사이트 모양이 바뀌었을 수 있음)')
    return rows


def save(conn, rows: list[dict]) -> list[dict]:
    """새 공지만 초안으로 저장. 이미 초안이거나 공지로 올라간 링크는 건너뜀"""
    oldest = now().date() - timedelta(days=MAX_AGE_DAYS)
    new = []
    for x in rows:
        if x['date'] < oldest:
            continue
        if conn.execute('insert into notice_draft (id, title, notice_date, source_url) select %s, %s, %s, %s '
                        'where not exists (select 1 from notice where source_url = %s) on conflict do nothing returning id',
                        (x['id'], x['title'], x['date'], x['url'], x['url'])).fetchone():
            new.append(x)
    return new


def notify(new: list[dict]) -> None:
    """운영자에게 메일 (SNS 주제 NOTICE_SNS_TOPIC_ARN 이 있을 때만). 실패해도 초안은 남음"""
    topic = env('NOTICE_SNS_TOPIC_ARN')
    if not (topic and new):
        return
    import boto3
    body = '\n\n'.join(f"[{x['date']}] {x['title']}\n{x['url']}" for x in new)
    try:
        boto3.client('sns', region_name=env('AWS_REGION', 'ap-northeast-2')).publish(
            TopicArn=topic, Subject=f'Gyeongbokgung notice drafts: {len(new)}',
            Message=f'확인할 새 공지 초안 {len(new)}건\n\n{body}\n\n운영자 API /api/admin/notice-drafts 에서 승인하거나 거절하세요.')
    except Exception:
        log.exception('초안 알림 실패')


def run(conn, client: httpx.Client | None = None) -> list[dict]:
    """한 번 수집. 결과는 notice_collect 에 남겨 운영자가 언제까지 잘 됐는지 볼 수 있게 함"""
    try:
        new = save(conn, fetch(client))
    except CollectError as e:
        conn.execute('insert into notice_collect (id, last_error, last_error_at) values (1, %s, now()) '
                     'on conflict (id) do update set last_error = excluded.last_error, last_error_at = now()', (str(e)[:500],))
        raise
    conn.execute('insert into notice_collect (id, last_ok_at) values (1, now()) '
                 'on conflict (id) do update set last_ok_at = now(), last_error = null')
    notify(new)
    return new
