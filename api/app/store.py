"""라이브 세션 진행 중 상태 (Redis, ERD v0.1 5.2). api 와 realtime 컨테이너가 같이 씀.

  session:{code}            hash   status, micOn, startedAt, guideName, location(해설사 현재 위치 poiId)
  session:{code}:listeners  hash   연결 id → 언어
  session:{code}:peak       hash   언어 → 최대 동시 인원, _total → 전체 최대
  session:{code}:cards      hash   카드 id → 언급 횟수
  session:{code}:seq        string 자막 순번
  채널 session:{code}:sub:{lang}  언어별 자막        → 관람객
       session:{code}:ctl         mic · session_ended → 관람객
       session:{code}:guide       presence · transcript → 해설사
자막 문장은 저장하지 않음 (재전송 버퍼 없음 → 놓친 구간은 gap 으로만 알림, 기능 명세서 17-3 제안안)."""
import json
import os
from collections import Counter

import redis.asyncio as aioredis

ENDED_TTL = 3600  # 세션 종료 후 1시간 뒤 상태 삭제


def make_redis() -> aioredis.Redis:
    return aioredis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379/0'), decode_responses=True)


def key(code: str, *parts: str) -> str:
    return ':'.join(('session', code, *parts))


def sub_channel(code: str, lang: str) -> str:
    return key(code, 'sub', lang)


def ctl_channel(code: str) -> str:
    return key(code, 'ctl')


def guide_channel(code: str) -> str:
    return key(code, 'guide')


async def publish(r: aioredis.Redis, channel: str, msg: dict) -> None:
    await r.publish(channel, json.dumps(msg, ensure_ascii=False))


async def init_session(r, code: str, started_at: str, guide_name: str | None) -> None:
    await r.hset(key(code), mapping={'status': 'waiting', 'micOn': '0', 'startedAt': started_at, 'guideName': guide_name or ''})


async def set_location(r, code: str, poi_id: str) -> None:
    """해설사 폰이 알려 준 현재 해설 위치 → 위치별 STT 사전 (STT 벤치마크 v2 4.1)"""
    await r.hset(key(code), 'location', poi_id)


async def location(r, code: str) -> str | None:
    return await r.hget(key(code), 'location') or None


async def set_status(r, code: str, status: str) -> None:
    await r.hset(key(code), 'status', status)


async def mic_on(r, code: str) -> bool:
    return await r.hget(key(code), 'micOn') == '1'


async def set_mic(r, code: str, on: bool) -> None:
    await r.hset(key(code), 'micOn', '1' if on else '0')
    await publish(r, ctl_channel(code), {'type': 'mic', 'on': on})


async def presence(r, code: str) -> dict:
    langs = Counter(await r.hvals(key(code, 'listeners')))
    return {'type': 'presence', 'participants': sum(langs.values()), 'languages': dict(langs)}


async def _bump_peaks(r, code: str, p: dict) -> None:
    k = key(code, 'peak')
    current = await r.hgetall(k)
    for field, n in [('_total', p['participants']), *p['languages'].items()]:
        if n > int(current.get(field, 0)):
            await r.hset(k, field, n)


async def add_listener(r, code: str, conn: str, lang: str) -> None:
    await r.hset(key(code, 'listeners'), conn, lang)
    p = await presence(r, code)
    await _bump_peaks(r, code, p)
    await publish(r, guide_channel(code), p)


async def remove_listener(r, code: str, conn: str) -> None:
    await r.hdel(key(code, 'listeners'), conn)
    await publish(r, guide_channel(code), await presence(r, code))


async def listener_langs(r, code: str) -> set[str]:
    return set(await r.hvals(key(code, 'listeners')))


async def peaks(r, code: str) -> tuple[int, dict[str, int]]:
    p = {k: int(v) for k, v in (await r.hgetall(key(code, 'peak'))).items()}
    return p.pop('_total', 0), p


async def next_seq(r, code: str) -> int:
    return await r.incr(key(code, 'seq'))


async def current_seq(r, code: str) -> int:
    return int(await r.get(key(code, 'seq')) or 0)


async def count_cards(r, code: str, card_ids: list[str]) -> None:
    for cid in card_ids:
        await r.hincrby(key(code, 'cards'), cid, 1)


async def card_counts(r, code: str) -> dict[str, int]:
    return {k: int(v) for k, v in (await r.hgetall(key(code, 'cards'))).items()}


async def close_session(r, code: str) -> None:
    """종료: 관람객에게 알리고 진행 중 상태를 지움 (집계는 호출 전에 DB 로 옮겨 둠)"""
    await r.hset(key(code), mapping={'status': 'ended', 'micOn': '0'})
    await r.expire(key(code), ENDED_TTL)
    await publish(r, ctl_channel(code), {'type': 'session_ended'})
    await r.delete(*(key(code, p) for p in ('listeners', 'peak', 'cards', 'seq')))
