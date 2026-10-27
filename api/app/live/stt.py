"""해설사 음성 → 한국어 문장. STT 벤치마크 v2(4.3 권장 구성) 기준으로 엔진을 고름.

STT_PROVIDER
  whisper_http  1안 (기본). 집 서버 Z6 G4 + Whisper large-v3-turbo + 위치별 받아쓰기 사전.
                발화 하나 = binary 프레임 하나 (폰 VAD 가 자른 발화 전체, WAV 또는 WebM/Opus).
                STT_HTTP_URLS 를 앞에서부터 시도 → 1안이 멈추면 3안(Mac mini)으로 넘어감.
                서버 계약은 stt-server/ 참고: POST /transcribe (audio 파일 + prompt) → {"text": "..."}
  transcribe    2 대안 (집 장비 없이 클라우드). Amazon Transcribe 스트리밍 + 위치별 사용자 지정 어휘 + 후처리 사전.
                binary 프레임 = PCM 16bit mono AUDIO_SAMPLE_RATE(16000)Hz 조각.
  none          끔 (개발용, ALLOW_TEXT_INPUT 로 문장을 직접 넣음)
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.live.hints import Hints
from app.settings import env

log = logging.getLogger('gunggeum.stt')
OnFinal = Callable[[str], Awaitable[None]]
MAX_UTTERANCE_BYTES = 2_000_000  # 발화 하나 (Opus 24kbps 7.6초 ≈ 23KB, WAV 16kHz ≈ 243KB)


class NoSTT:
    utterance = False

    def __init__(self, on_final: OnFinal, hints: Hints):
        pass

    async def feed(self, chunk: bytes, location: str | None) -> None:
        pass

    async def close(self) -> None:
        pass


class WhisperHttpSTT:
    """집 서버 Whisper. 발화마다 HTTP 한 번, 위치별 사전을 prompt 로 같이 보냄"""
    utterance = True

    def __init__(self, on_final: OnFinal, hints: Hints, client=None):
        import httpx
        self.on_final, self.hints = on_final, hints
        self.urls = [u.strip().rstrip('/') for u in env('STT_HTTP_URLS').split(',') if u.strip()]
        self.token = env('STT_HTTP_TOKEN')
        self.client = client or httpx.AsyncClient(timeout=float(env('STT_HTTP_TIMEOUT', '5')))

    async def transcribe(self, audio: bytes, prompt: str) -> str:
        if not self.urls:
            raise RuntimeError('STT_HTTP_URLS 가 비어 있음')
        headers = {'Authorization': f'Bearer {self.token}'} if self.token else {}
        last: Exception | None = None
        for url in self.urls:  # 1안 → 3안 순서로
            try:
                res = await self.client.post(f'{url}/transcribe', headers=headers, data={'prompt': prompt, 'language': 'ko'},
                                             files={'audio': ('utterance', audio, 'application/octet-stream')})
                res.raise_for_status()
                return res.json()['text']
            except Exception as e:  # 연결 실패·시간 초과·5xx → 다음 서버
                log.warning('STT 서버 실패 %s: %r', url, e)
                last = e
        raise RuntimeError('모든 STT 서버 실패') from last

    async def feed(self, chunk: bytes, location: str | None) -> None:
        if len(chunk) > MAX_UTTERANCE_BYTES:
            raise ValueError('발화가 너무 큼')
        text = (await self.transcribe(chunk, self.hints.prompt(location))).strip()
        if text:
            await self.on_final(text)

    async def close(self) -> None:
        await self.client.aclose()


class TranscribeSTT:
    """Amazon Transcribe 스트리밍. 해설사 연결 하나에 스트림 하나.
    위치별 어휘: TRANSCRIBE_VOCABULARY_PREFIX + poiId 이름으로 미리 만들어 둔 사용자 지정 어휘를 씀 → 위치가 바뀌면 스트림을 새로 엶.
    오디오가 15초 넘게 안 오면 Transcribe 가 스트림을 닫으므로 다음 오디오에서 다시 엶. 과금은 1초 단위, 최소 요금 없음."""
    utterance = False

    def __init__(self, on_final: OnFinal, hints: Hints):
        self.on_final, self.hints = on_final, hints
        self.stream = None
        self.reader: asyncio.Task | None = None
        self.vocab: str | None = None

    def vocabulary(self, location: str | None) -> str | None:
        prefix = env('TRANSCRIBE_VOCABULARY_PREFIX')
        if prefix and location and self.hints.terms(location):
            return prefix + location.replace(':', '-')  # 어휘 이름에 ':' 를 못 씀
        return env('TRANSCRIBE_VOCABULARY') or None

    async def _open(self, vocab: str | None) -> None:
        from amazon_transcribe.client import TranscribeStreamingClient
        client = TranscribeStreamingClient(region=env('AWS_REGION', 'ap-northeast-2'))
        extra = {'vocabulary_name': vocab} if vocab else {}
        self.stream = await client.start_stream_transcription(
            language_code='ko-KR', media_sample_rate_hz=int(env('AUDIO_SAMPLE_RATE', '16000')), media_encoding='pcm', **extra)
        self.vocab = vocab
        self.reader = asyncio.create_task(self._read(self.stream))

    async def _read(self, stream) -> None:
        from amazon_transcribe.model import TranscriptEvent
        try:
            async for event in stream.output_stream:
                if not isinstance(event, TranscriptEvent):
                    continue
                for result in event.transcript.results:
                    if not result.is_partial and result.alternatives:  # 확정 문장만 자막으로
                        await self.on_final(result.alternatives[0].transcript)
        except Exception:
            log.exception('Transcribe 스트림 읽기 실패')
        finally:
            if self.stream is stream:
                self.stream = None

    async def feed(self, chunk: bytes, location: str | None) -> None:
        vocab = self.vocabulary(location)
        if self.stream is not None and vocab != self.vocab:  # 위치가 바뀜 → 그 위치 어휘로 다시 엶
            await self.close()
        if self.stream is None:
            await self._open(vocab)
        await self.stream.input_stream.send_audio_event(audio_chunk=chunk)

    async def close(self) -> None:
        stream, reader = self.stream, self.reader
        self.stream = self.reader = None
        if stream is not None:
            try:
                await stream.input_stream.end_stream()
            except Exception:
                pass
        if reader is not None:
            try:
                await asyncio.wait_for(reader, timeout=5)
            except Exception:
                reader.cancel()


PROVIDERS = {'whisper_http': WhisperHttpSTT, 'transcribe': TranscribeSTT, 'none': NoSTT}


def provider() -> str:
    return env('STT_PROVIDER', 'whisper_http')


def make_stt(on_final: OnFinal, hints: Hints):
    return PROVIDERS[provider()](on_final, hints)


def needs_postcorrect() -> bool:
    """후처리 사전: STT_POSTCORRECT=1/0 로 강제, 비우면 받아쓰기 사전이 약한 엔진(transcribe)만 (보고서 4.1)"""
    value = env('STT_POSTCORRECT').lower()
    if value in ('1', 'true', 'yes'):
        return True
    if value in ('0', 'false', 'no'):
        return False
    return provider() == 'transcribe'
