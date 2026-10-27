"""라이브 투어 WebSocket (API 명세서 v0.1 7.6).

  wss://{host}/ws/sessions/{code}/guide?token=<guideToken>   해설사 (G-03)
     ← binary 오디오 (whisper_http: 발화 하나 = 프레임 하나 / transcribe: PCM 조각) · {"type":"location","poiId":"..."}
       · {"type":"mic","on":bool} · {"type":"ping"} · (개발용) {"type":"text","textKo":"..."}
     → {"type":"presence",...} · {"type":"transcript","seq","textKo"} · {"type":"mic"} · {"type":"session_ended"}
       · {"type":"pong"} · {"type":"error","message"}
  wss://{host}/ws/sessions/{code}/listen?lang=en            관람객 (T-31)
     ← {"type":"ping"} · {"type":"resume","lastSeq":37}
     → {"type":"subtitle",...} · {"type":"gap","fromSeq","toSeq"} · {"type":"mic","on"} · {"type":"session_ended"} · {"type":"pong"}

닫는 코드: 4400 잘못된 언어 · 4401 토큰 오류 · 4404 없는 세션 · 4410 이미 끝난 세션 · 1000 세션 종료."""
import asyncio
import json
import logging
import uuid
from contextlib import suppress

import re

from fastapi import APIRouter, WebSocket

from app import store
from app.db import ensure_schema
from app.live.stt import make_stt
from app.routes.sessions import fetch, mark_live, token_ok
from app.settings import LANGS, flag

log = logging.getLogger('gunggeum.live')
router = APIRouter()
POI_ID = re.compile(r'[\w:.\-]{1,80}')  # pois.json 의 id


class Socket:
    """보내기를 한 줄로 세움 (자막 전달 태스크와 pong 응답이 동시에 보낼 수 있어서)"""

    def __init__(self, ws: WebSocket):
        self.ws, self.lock = ws, asyncio.Lock()

    async def send(self, msg: dict | str) -> None:
        async with self.lock:
            await self.ws.send_text(msg if isinstance(msg, str) else json.dumps(msg, ensure_ascii=False))


async def forward(sock: Socket, pubsub, stop_on_end: bool) -> None:
    """Redis 채널 → WebSocket. stop_on_end 면 session_ended 를 전한 뒤 끝냄"""
    while True:
        m = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if m is None:
            continue
        await sock.send(m['data'])
        if stop_on_end and json.loads(m['data']).get('type') == 'session_ended':
            return


async def inbox(ws: WebSocket):
    """받은 프레임을 하나씩 (bytes 또는 dict). 연결이 끊기면 끝"""
    while True:
        msg = await ws.receive()
        if msg['type'] == 'websocket.disconnect':
            return
        if msg.get('bytes') is not None:
            yield msg['bytes']
        elif msg.get('text') is not None:
            with suppress(json.JSONDecodeError):
                data = json.loads(msg['text'])
                if isinstance(data, dict):
                    yield data


async def run_until_first(*coros) -> None:
    tasks = [asyncio.ensure_future(c) for c in coros]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with suppress(BaseException):
                await t


async def finish(coro) -> None:
    """정리 작업은 핸들러가 취소돼도 끝까지 돌게 함 (관람객 수·마이크 상태가 Redis 에 남지 않게)"""
    await asyncio.shield(asyncio.ensure_future(coro))


async def open_session(ws: WebSocket, code: str):
    """accept 후 세션 행을 찾음. 없으면 4404 로 닫고 None"""
    await ws.accept()
    pool = await ensure_schema(ws.app.state.pool)
    row = await fetch(pool, code)
    if row is None:
        await ws.close(code=4404)
    return pool, row


@router.websocket('/ws/sessions/{code}/listen')
async def listen(ws: WebSocket, code: str, lang: str = 'en'):
    pool, row = await open_session(ws, code)
    if row is None:
        return
    if lang not in LANGS:
        return await ws.close(code=4400)
    sock, r = Socket(ws), ws.app.state.redis
    if row['status'] == 'ended':
        await sock.send({'type': 'session_ended'})
        return await ws.close(code=1000)

    conn = uuid.uuid4().hex
    pubsub = r.pubsub()
    await pubsub.subscribe(store.sub_channel(code, lang), store.ctl_channel(code))
    await store.add_listener(r, code, conn, lang)
    ended = False
    try:
        await sock.send({'type': 'mic', 'on': await store.mic_on(r, code)})

        async def from_listener():
            async for msg in inbox(ws):
                if not isinstance(msg, dict):
                    continue
                if msg.get('type') == 'ping':
                    await sock.send({'type': 'pong'})
                elif msg.get('type') == 'resume':  # 재연결: 놓친 순번을 알려 줌 (자막 재전송은 안 함)
                    last, current = int(msg.get('lastSeq') or 0), await store.current_seq(r, code)
                    if current > last:
                        await sock.send({'type': 'gap', 'fromSeq': last + 1, 'toSeq': current})

        async def to_listener():
            nonlocal ended
            await forward(sock, pubsub, stop_on_end=True)
            ended = True

        await run_until_first(from_listener(), to_listener())
    finally:
        async def cleanup():
            await store.remove_listener(r, code, conn)
            await pubsub.unsubscribe()
            await pubsub.aclose()
            if ended:
                with suppress(Exception):
                    await ws.close(code=1000)
        await finish(cleanup())


@router.websocket('/ws/sessions/{code}/guide')
async def guide(ws: WebSocket, code: str, token: str = ''):
    pool, row = await open_session(ws, code)
    if row is None:
        return
    if not token_ok(row, token):
        return await ws.close(code=4401)
    if row['status'] == 'ended':
        return await ws.close(code=4410)

    sock, r, pipeline = Socket(ws), ws.app.state.redis, ws.app.state.pipeline
    await mark_live(pool, r, code)
    pubsub = r.pubsub()
    await pubsub.subscribe(store.guide_channel(code), store.ctl_channel(code))  # ctl: 다른 기기에서 종료해도 알 수 있게
    stt = make_stt(lambda text: pipeline.handle(code, text), pipeline.hints)
    ended = False
    try:
        await sock.send(await store.presence(r, code))

        async def from_guide():
            stt_failed = False
            async for msg in inbox(ws):
                if isinstance(msg, bytes):
                    try:
                        await stt.feed(msg, await store.location(r, code))
                        stt_failed = False
                    except Exception:
                        log.exception('음성 인식 실패 %s', code)
                        if not stt_failed:  # 같은 오류를 프레임마다 보내지 않음
                            await sock.send({'type': 'error', 'message': '음성 인식 연결에 실패했습니다'})
                        stt_failed = True
                elif msg.get('type') == 'location' and POI_ID.fullmatch(str(msg.get('poiId') or '')):
                    await store.set_location(r, code, msg['poiId'])  # 위치별 STT 사전을 바꿈
                elif msg.get('type') == 'mic':
                    await store.set_mic(r, code, bool(msg.get('on')))
                elif msg.get('type') == 'ping':
                    await sock.send({'type': 'pong'})
                elif msg.get('type') == 'text' and flag('ALLOW_TEXT_INPUT'):  # 개발용: STT 없이 문장을 직접 넣음
                    await pipeline.handle(code, str(msg.get('textKo') or ''))

        async def to_guide():
            nonlocal ended
            await forward(sock, pubsub, stop_on_end=True)
            ended = True

        await run_until_first(from_guide(), to_guide())
    finally:
        async def cleanup():
            await stt.close()
            latest = await fetch(pool, code)
            if latest and latest['status'] != 'ended':
                await store.set_mic(r, code, False)  # 해설사가 끊기면 관람객 화면에 S-04 (마이크 꺼짐)
            await pubsub.unsubscribe()
            await pubsub.aclose()
            if ended:
                with suppress(Exception):
                    await ws.close(code=1000)
        await finish(cleanup())
