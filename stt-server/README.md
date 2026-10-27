# stt-server (집 서버 음성 인식)

STT 벤치마크 v2의 권장 구성 1안(Z6 G4 + Whisper large-v3-turbo)과 3안(Mac mini 대체)을 띄우는 작은 HTTP 서버입니다. EC2의 realtime 컨테이너가 해설사 발화마다 `POST /transcribe`로 부릅니다.

## 실행 (Z6 G4, Ubuntu + NVIDIA)
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
```bash
STT_SERVER_TOKEN=<긴 임의 문자열> .venv/bin/uvicorn app:app --host 0.0.0.0 --port 9000
```
- 처음 뜰 때 모델(약 1.6GB)을 받습니다. `WHISPER_MODEL`로 바꿀 수 있습니다.
- CUDA가 있으면 float16, 없으면 CPU int8로 돕니다 (`WHISPER_DEVICE`, `WHISPER_COMPUTE`).

## EC2 → 집 서버 연결
집 공유기에 포트를 직접 열지 않습니다. EC2와 집 서버를 같은 사설망으로 묶는 터널(예: Tailscale, WireGuard, Cloudflare Tunnel)을 쓰고, realtime의 `STT_HTTP_URLS`에 터널 주소를 넣습니다.
```
STT_HTTP_URLS=http://z6g4.<tailnet>:9000,http://macmini.<tailnet>:9000
STT_HTTP_TOKEN=<위와 같은 토큰>
```
앞 주소가 실패하면(연결 실패, 5초 초과, 5xx) 다음 주소로 넘어갑니다.

## 계약
| | |
|---|---|
| 요청 | `POST /transcribe` multipart: `audio`(발화 하나), `prompt`(위치별 받아쓰기 사전), `language`(`ko`) |
| 인증 | `Authorization: Bearer <STT_SERVER_TOKEN>` |
| 응답 | `{"text": "이곳은 근정전입니다.", "seconds": 0.28}` |
| 저장 | 하지 않음 (메모리에서 처리 후 버림) |
