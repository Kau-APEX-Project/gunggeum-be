"""집 서버 STT (STT 벤치마크 v2 4.3 권장 구성 1안·3안).

  1안  Z6 G4 (RTX 2070)  WHISPER_BACKEND=faster (기본)  faster-whisper float16   벤치마크 발화당 0.28초
  3안  Mac mini (M1)      WHISPER_BACKEND=mlx            mlx-whisper fp16         벤치마크 발화당 1.61초
  (맥에서 faster-whisper 는 CPU 로만 돌아 발화당 7초대 → 맥은 반드시 mlx)

realtime 컨테이너(app/live/stt.py WhisperHttpSTT)가 발화마다 부름:
  POST /transcribe   multipart: audio(발화 하나, WAV·WebM/Opus 등 ffmpeg 가 읽는 형식), prompt(위치별 받아쓰기 사전), language(ko)
                     헤더 Authorization: Bearer <STT_SERVER_TOKEN>  (토큰을 정했으면)
  → 200 {"text": "...", "seconds": 0.28}
  GET  /health       → {"status": "ok", "model": "..."}

받은 음성은 메모리에서만 처리하고 저장하지 않음 (G-01 동의 문구).
"""
import io
import os
import time

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

BACKEND = os.environ.get('WHISPER_BACKEND', 'faster')
DEFAULT_MODEL = {'faster': 'mobiuslabsgmbh/faster-whisper-large-v3-turbo', 'mlx': 'mlx-community/whisper-large-v3-turbo'}
MODEL = os.environ.get('WHISPER_MODEL', DEFAULT_MODEL[BACKEND])  # 벤치마크와 같은 모델
TOKEN = os.environ.get('STT_SERVER_TOKEN', '')
MAX_BYTES = 2_000_000

app = FastAPI(title='宮今 STT', docs_url=None, redoc_url=None)
_model = None


def model():
    global _model
    if _model is None and BACKEND == 'faster':
        from faster_whisper import WhisperModel
        device = os.environ.get('WHISPER_DEVICE', 'auto')
        compute = os.environ.get('WHISPER_COMPUTE', 'default')  # cuda 면 float16, cpu 면 int8 이 기본
        _model = WhisperModel(MODEL, device=device, compute_type=compute)
    return _model


def run(data: bytes, language: str, prompt: str) -> str:
    """발화 하나 → 문장. 디스크에 쓰지 않고 메모리에서 디코딩 (PyAV, 16kHz mono)"""
    if BACKEND == 'mlx':
        import mlx_whisper
        from faster_whisper.audio import decode_audio
        out = mlx_whisper.transcribe(decode_audio(io.BytesIO(data)), path_or_hf_repo=MODEL, language=language,
                                     initial_prompt=prompt or None, condition_on_previous_text=False, fp16=True)
        return out['text'].strip()
    segments, _ = model().transcribe(
        io.BytesIO(data), language=language, initial_prompt=prompt or None,
        vad_filter=False,                   # 발화 자르기는 해설사 폰 VAD 가 이미 함
        condition_on_previous_text=False,   # 앞 문장에 끌려 반복 출력하는 붕괴 방지
    )
    return ''.join(s.text for s in segments).strip()


@app.on_event('startup')
def warm_up():
    """첫 발화가 모델 로딩 시간을 먹지 않게 무음 1초로 한 번 돌려 둠"""
    import wave
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b'\0\0' * 16000)
    run(buf.getvalue(), 'ko', '')


@app.get('/health')
def health():
    return {'status': 'ok', 'backend': BACKEND, 'model': MODEL}


@app.post('/transcribe')
def transcribe(audio: UploadFile = File(...), prompt: str = Form(''), language: str = Form('ko'),
               authorization: str | None = Header(default=None)):
    if TOKEN and authorization != f'Bearer {TOKEN}':
        raise HTTPException(401, 'token')
    data = audio.file.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(400, 'audio')
    t = time.perf_counter()
    text = run(data, language, prompt)
    return {'text': text, 'seconds': round(time.perf_counter() - t, 3)}
