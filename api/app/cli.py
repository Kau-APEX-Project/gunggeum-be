"""운영자 도구: 해설 일정·공지 입력 (관리자 화면이 없어서 명령으로 넣음).

  docker compose exec api python -m app.cli tours add 2026-10-27 10:00 11:00 13:00 14:00 15:00 16:00
  docker compose exec api python -m app.cli tours list 2026-10-27
  docker compose exec api python -m app.cli notices add --type tour_cancelled \\
      --title "오늘 14:00 영어 해설 우천 취소" --body "..." --translate
  docker compose exec api python -m app.cli notices list

--translate 는 Amazon Translate(TRANSLATE_PROVIDER=aws)로 영어·태국어를 만듦. 직접 넣으려면 --en-title/--en-body/--th-title/--th-body.
"""
import argparse
import asyncio
import os
import sys

import psycopg
from psycopg.rows import dict_row

from app.db import SCHEMA
from app.settings import now


def connect():
    c = psycopg.connect(os.environ['DATABASE_URL'], autocommit=True, row_factory=dict_row)
    c.execute(SCHEMA)
    return c


def tours(args):
    with connect() as c:
        if args.action == 'add':
            for t in args.times:
                c.execute('insert into tour_schedule (tour_date, start_time, duration_min) values (%s, %s::time, %s) '
                          'on conflict (tour_date, start_time) do update set duration_min = excluded.duration_min',
                          (args.date, t, args.duration))
        if args.action == 'delete':
            for t in args.times:
                c.execute('delete from tour_schedule where tour_date = %s and start_time = %s::time', (args.date, t))
        for x in c.execute('select start_time, duration_min, session_code from tour_schedule where tour_date = %s '
                           'order by start_time', (args.date,)):
            print(f"{x['start_time']:%H:%M}  {x['duration_min']}분  {x['session_code'] or '-'}")


def notices(args):
    with connect() as c:
        if args.action == 'add':
            if not (args.title and args.body and args.type):
                sys.exit('--type --title --body 가 필요합니다')
            day = now().strftime('%Y%m%d')
            n = c.execute("select count(*) as n from notice where id like %s", (f'n-{day}-%',)).fetchone()['n']
            nid = f'n-{day}-{n + 1:02d}'
            c.execute('insert into notice (id, type, title, body, source_url, published_at) values (%s, %s, %s, %s, %s, %s)',
                      (nid, args.type, args.title, args.body, args.url, now()))
            tr = {'en': (args.en_title, args.en_body), 'th': (args.th_title, args.th_body)}
            if args.translate:
                from app.live.translate import make_translator
                t = make_translator()
                for lang in tr:
                    tr[lang] = tuple(asyncio.run(t.translate(x, lang)) for x in (args.title, args.body))
            for lang, (title, body) in tr.items():
                if title and body:
                    c.execute('insert into notice_translation values (%s, %s, %s, %s)', (nid, lang, title, body))
            print('추가:', nid)
        if args.action == 'delete':
            c.execute('delete from notice where id = %s', (args.id,))
        for x in c.execute('select n.id, n.type, n.title, array_agg(t.lang) filter (where t.lang is not null) as langs '
                           'from notice n left join notice_translation t on t.notice_id = n.id '
                           'group by n.id order by n.published_at desc limit 20'):
            print(f"{x['id']}  {x['type']:<15} {x['title']}  [{', '.join(x['langs'] or []) or '번역 없음'}]")


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m app.cli')
    sub = p.add_subparsers(dest='cmd', required=True)
    t = sub.add_parser('tours', help='해설 일정')
    t.add_argument('action', choices=['add', 'delete', 'list'])
    t.add_argument('date', help='YYYY-MM-DD')
    t.add_argument('times', nargs='*', help='HH:MM ...')
    t.add_argument('--duration', type=int, default=60, help='해설 길이(분)')
    t.set_defaults(fn=tours)
    n = sub.add_parser('notices', help='공지')
    n.add_argument('action', choices=['add', 'delete', 'list'])
    n.add_argument('--id')
    n.add_argument('--type', choices=['tour_cancelled', 'weather', 'event_change'])
    n.add_argument('--title')
    n.add_argument('--body')
    n.add_argument('--url', help='원문 URL (중복 방지)')
    n.add_argument('--translate', action='store_true')
    for lang in ('en', 'th'):
        n.add_argument(f'--{lang}-title')
        n.add_argument(f'--{lang}-body')
    n.set_defaults(fn=notices)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == '__main__':
    main()
