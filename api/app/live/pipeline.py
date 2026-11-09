"""확정된 한국어 문장 하나 → 언어별 자막 (아키텍처 6.4 의 3~5단계).

  후처리 사전(위치별, 약한 엔진만) → 순번(seq) → 해설사에게 인식 문장 미리보기(transcript)
  → 참여 언어마다 번역(언어 수만큼, 사람 수 아님) → 카드 링크 → Redis 채널로 발행
카드 링크·카드 id 는 팀 로직 cards.link_names 를 그대로 씀 (답변과 같은 [이름](card:id) 형식)."""
import asyncio
import logging
import re

import psycopg

from app import store
from app.core import use_vendor
from app.live import postcorrect
from app.live.hints import Hints
from app.live.stt import needs_postcorrect
from app.live.translate import make_translator
from app.settings import iso, now

log = logging.getLogger('gunggeum.live')
LANG_NAMES = {'en': 'English', 'th': 'ภาษาไทย', 'ko': '한국어'}  # cards.link_names 가 받는 언어 이름
CARD_LINK = re.compile(r'\(card:([bt]-\d+)\)')


def correct(text_ko: str, terms: list[str]) -> str:
    """고유명사 교정 = 자주 틀리는 표기 표(정확 일치) → 위치별 후처리 사전 (STT 벤치마크 v2: 자모 Jaro-Winkler 0.85).
    받아쓰기 사전을 넣은 엔진에는 안 씀 (STT_POSTCORRECT)"""
    if not needs_postcorrect():
        return text_ko
    return postcorrect.correct(postcorrect.apply_corrections(text_ko), terms)


def card_ids(text: str) -> list[str]:
    return list(dict.fromkeys(CARD_LINK.findall(text)))


class Linker:
    """콘텐츠 DB(docs)의 전각·용어 메타데이터를 한 번 읽어 두고 문장 속 이름에 카드 링크를 붙임"""

    def __init__(self, pool):
        self.pool, self.metas = pool, None

    async def load(self) -> list[dict]:
        if self.metas is None:
            try:
                async with self.pool.connection() as c:
                    rows = await (await c.execute(
                        "select meta from docs where meta->>'type' in ('building', 'term') order by pos")).fetchall()
                self.metas = [x['meta'] for x in rows]
            except psycopg.errors.UndefinedTable:
                log.warning('docs 테이블이 없어 카드 링크 없이 자막을 보냄')
                self.metas = []
        return self.metas

    async def link(self, text: str, lang: str) -> str:
        use_vendor()
        import cards
        return cards.link_names(text, await self.load(), LANG_NAMES[lang])


class Pipeline:
    def __init__(self, pool, r, translator, linker, hints: Hints):
        self.pool, self.r, self.translator, self.linker, self.hints = pool, r, translator, linker, hints

    async def handle(self, code: str, text_ko: str) -> None:
        r = self.r
        text_ko = correct(text_ko.strip(), self.hints.terms(await store.location(r, code)))
        if not text_ko:
            return
        seq, ts = await store.next_seq(r, code), iso(now())
        await store.publish(r, store.guide_channel(code), {'type': 'transcript', 'seq': seq, 'textKo': text_ko})
        linked_ko = await self.linker.link(text_ko, 'ko')
        await store.count_cards(r, code, card_ids(linked_ko))  # T-32 언급 카드 (언어와 무관하게 한국어 기준)

        async def one(lang: str) -> None:
            text = linked_ko if lang == 'ko' else await self.linker.link(await self.translator.translate(text_ko, lang), lang)
            await store.publish(r, store.sub_channel(code, lang), {
                'type': 'subtitle', 'seq': seq, 'timestamp': ts, 'textKo': text_ko, 'text': text,
                'lang': lang, 'cardIds': card_ids(text)})

        langs = sorted(await store.listener_langs(r, code))
        results = await asyncio.gather(*(one(x) for x in langs), return_exceptions=True)
        for lang, res in zip(langs, results):
            if isinstance(res, Exception):  # 한 언어 번역이 실패해도 다른 언어는 나감 → 그 언어는 gap 으로 보임
                log.error('자막 실패 %s seq=%s lang=%s: %r', code, seq, lang, res)


def make_pipeline(pool, r) -> Pipeline:
    return Pipeline(pool, r, make_translator(), Linker(pool), Hints.load())
