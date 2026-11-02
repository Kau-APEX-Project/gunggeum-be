# gunggeum-be

宮今(궁금) 경복궁 외국인 관광객 안내 서비스의 백엔드입니다. API 명세서 v0.1의 엔드포인트 13개(REST 11 + WebSocket 2)와, EC2 한 대에서 돌릴 Docker Compose 구성(Nginx · API 서비스 · 실시간 통역 · PostgreSQL · Redis)을 담습니다.

아키텍처와 제안서 대비 바뀐 점: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

> 조직 BE 리포가 생기기 전까지 로컬에서 진행합니다. 리포가 생기면 `git remote add origin ...` 후 push 하면 기록이 그대로 올라갑니다.

## 구성

```
폰 ── CloudFront ─┬─ /api/*  → EC2 :80 Nginx ─→ api      (REST, :8000) ─┬→ db (PostgreSQL + pgvector)
                  ├─ /ws/*   ─────────────────→ realtime (WS,   :8001) ─┼→ redis (세션 상태 · 자막 Pub/Sub)
                  │                                                       ├→ OpenAI(GPT-6 Luna) · Bedrock(Titan) · Translate
                  │                                                       └→ 집 STT 서버 (Whisper turbo, 사설 터널)
                  └─ 그 밖   → S3 (visit/ · servermap/ · photos/)
```

```
gunggeum-be/
├─ docker-compose.yml   nginx · api · realtime · db · redis
├─ .env.example         키·설정 양식 → .env 로 복사
├─ nginx/               라우팅 · IP 별 속도 제한 · JSON 에러 · WebSocket 3시간
├─ db/                  콘텐츠 DB 초기 데이터 (팀 deploy/db 복사본, 문서 585개 + 임베딩)
├─ docs/                ARCHITECTURE.md (v0.2) · 노션용 기능명세서
├─ stt-server/          집 서버 음성 인식 (1안 Z6 G4 faster-whisper · 3안 Mac mini mlx)
└─ api/                 api · realtime 두 컨테이너가 같은 코드를 씀
   ├─ app/
   │  ├─ main.py          api 컨테이너 앱
   │  ├─ factory.py       앱 만들기 (REST / WS 선택)
   │  ├─ routes/          content.py 질문·카드·코스 · sessions.py 세션 · ops.py 일정·공지·집계
   │  ├─ live/            realtime 컨테이너: routes.py WS · pipeline.py 후처리→번역→카드 링크
   │  │                   · stt.py (whisper_http · transcribe · none) · hints.py 위치별 사전 · postcorrect.py · translate.py
   │  ├─ core.py          팀 로직(vendor) 연결
   │  ├─ db.py · store.py 운영 DB 테이블 · Redis 키
   │  └─ cli.py           운영자 도구 (해설 일정 · 공지 입력)
   ├─ vendor/gunggeum_server/   팀 deploy/server 복사본 (수정 금지, 출처는 SOURCE.md)
   ├─ data/               위치별 STT 사전 예시 (stt_hints.example.json)
   └─ tests/              55개
```

## API

서버를 띄우면 http://localhost:8080/api/docs 에서 REST를 직접 눌러 볼 수 있습니다 (WebSocket은 Swagger에 안 나옴).

| 메서드 | 경로 | 화면 | 비고 |
|---|---|---|---|
| POST | `/api/ask` | T-41~T-44 | 팀 로직 `ask.reply`. 선택 `language`(ko·en·th), 응답 `language` 도 코드 |
| GET | `/api/card?id=` | PNC | 팀 로직 `cards.card`, 하루 캐시 |
| POST | `/api/course` | T-14, T-15 | 팀 로직 `course.Planner`. `request`·`question` 은 1~300자 (넘으면 400) |
| GET | `/api/health` | 배포 확인 | `{"status":"ok","version":...}`, DB·LLM 안 부름 |
| GET | `/api/notices?lang=&since=` | T-10, T-50 | 번역 없으면 한국어 원문(`lang: ko`) |
| GET | `/api/tours/today` | T-30 | |
| POST | `/api/sessions` | G-01 | `consent` 필수, `GUIDE_ACCESS_CODE` 가 있으면 `accessCode` 필수, 선택 `tourTime` |
| GET | `/api/sessions/{code}` | T-31, G-02 | |
| POST | `/api/sessions/{code}/end` | G-03 | `Authorization: Bearer <guideToken>` |
| GET | `/api/sessions/{code}/summary` | T-32, G-04 | |
| POST | `/api/stats/visits` | T-51 | 204, 오늘 ±1일만 |
| WS | `/ws/sessions/{code}/guide?token=` | G-03 | 발화 오디오(binary) · `location` · `mic` · `ping` · (개발용) `text` |
| WS | `/ws/sessions/{code}/listen?lang=en` | T-31 | `subtitle` · `gap` · `mic` · `session_ended` · `pong` |

| POST · GET · DELETE | `/api/admin/notices`, `/api/admin/tours` | 운영자 | 공지·해설 일정 입력. `Authorization: Bearer <ADMIN_TOKEN>` (비우면 꺼짐) |
| GET | `/api/dev/live-tester` | 개발용 | 라이브 투어 브라우저 테스트 페이지 (`DEV_TOOLS=1`일 때만) |

에러는 모두 `{"error": "..."}`. WebSocket 닫는 코드: 4400 잘못된 언어 · 4401 토큰 오류 · 4404 없는 세션 · 4410 끝난 세션.

## 실행

### 1. 설정
```bash
cp .env.example .env
```
키 없이도 전부 뜹니다. 질문·카드·코스만 `OPENAI_API_KEY`·AWS 키가 있어야 답하고, 라이브 투어는 기본값(`STT_PROVIDER=none`, `TRANSLATE_PROVIDER=echo`, `ALLOW_TEXT_INPUT=1`)이면 해설사 소켓에 문장을 직접 넣어 흐름을 확인할 수 있습니다.

실제 음성으로 확인하려면 이 맥에서 STT 서버를 띄우고(아래), `.env`에 `STT_PROVIDER=whisper_http`, `STT_HTTP_URLS=http://host.docker.internal:9000`, `STT_HTTP_TOKEN=<토큰>`을 넣습니다.
```bash
cd stt-server && python3 -m venv .venv && .venv/bin/pip install -r requirements-mlx.txt
```
```bash
cd stt-server && WHISPER_BACKEND=mlx STT_SERVER_TOKEN=devtoken .venv/bin/uvicorn app:app --host 0.0.0.0 --port 9000
```

### 2. 전부 띄우기
```bash
docker compose up -d --build
```
```bash
curl http://localhost:8080/api/health
```

### 3. 테스트
db 컨테이너가 떠 있어야 운영 DB 테스트가 돕니다 (없으면 건너뜀).
```bash
cd api && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest -q
```

### 라이브 투어 직접 시험
http://localhost:8080/api/dev/live-tester 에서 세션 만들기 → 해설사·관람객 소켓 연결 → 위치·마이크·문장(또는 녹음) 보내기 → 자막·카드 확인까지 할 수 있습니다. 두 탭에서 열어 해설사와 관람객을 나눠도 됩니다.

### 운영자 도구 (해설 일정 · 공지)
`/api/docs`의 `/api/admin/*` 항목에서 `authorization` 칸에 `Bearer <ADMIN_TOKEN>`을 넣고 실행하거나, 서버에서 명령으로 넣습니다.
```bash
docker compose exec api python -m app.cli tours add 2026-10-27 10:00 11:00 13:00 14:00 15:00 16:00
```
```bash
docker compose exec api python -m app.cli notices add --type tour_cancelled --title "오늘 14:00 영어 해설 우천 취소" --body "..." --translate
```

### API만 직접 띄우기 (코드 고칠 때)
```bash
docker compose up -d db redis
```
redis 포트는 밖으로 안 열려 있으므로, 직접 띄울 때는 `docker-compose.yml`의 redis에 `ports: ["127.0.0.1:6379:6379"]`를 잠깐 추가합니다.
```bash
cd api && set -a && . ../.env && set +a && .venv/bin/uvicorn app.main:app --reload --port 8000
```

## 온프레미스 개발 서버 공개 (Cloudflare Tunnel)
배포 단계 전까지는 팀 장비에서 돌리고, 이미 있는 Cloudflare 도메인의 서브도메인으로 HTTPS 공개합니다. 폰에서 마이크·GPS를 쓰려면 HTTPS가 필요합니다.

1. Cloudflare 대시보드 → Zero Trust → Networks → Tunnels → 터널 만들기(Docker) → **토큰**을 `.env`의 `CLOUDFLARE_TUNNEL_TOKEN`에 넣음
2. 같은 터널의 Public Hostname: `gunggeum-dev.<도메인>` → 서비스 `HTTP` · `nginx:80`
3. `.env`: `PUBLIC_BASE_URL=https://gunggeum-dev.<도메인>` (QR 참여 링크), FE 개발 서버가 다른 주소면 `CORS_ORIGINS`에 추가
4. 띄우기
```bash
docker compose --profile tunnel up -d
```
- Nginx는 기본으로 이 PC 안(`127.0.0.1`)에서만 받으므로 밖에서는 터널로만 들어옵니다. 관람객 IP는 Cloudflare의 `CF-Connecting-IP`로 구분합니다 (요청 제한 기준).
- `/api/docs`, `/api/dev/*`, `/api/admin/*`는 Cloudflare Access(무료, 팀원 이메일 로그인)로 막아 두는 것을 권장합니다.

## 배포 메모 (EC2 t4g.medium)
- `HTTP_BIND=0.0.0.0`, `HTTP_PORT=80`, 보안 그룹 80은 CloudFront 관리형 프리픽스 리스트(`com.amazonaws.global.cloudfront.origin-facing`)만 허용.
- CloudFront `/api/*`·`/ws/*` 동작: 캐시 끔(`/api/card`만 캐시 허용), 오리진 요청 정책에 `CloudFront-Viewer-Address` 헤더 포함 (Nginx 속도 제한이 관람객 IP를 씀).
- CloudFront 오리진 응답 제한 시간 기본 30초 → 코스(10~20초) 여유를 위해 60초 권장.
- 운영 `.env`: `GUIDE_ACCESS_CODE` 채움, `STT_PROVIDER=whisper_http` + `STT_HTTP_URLS`(터널 주소, 1안·3안 순서) + `STT_HTTP_TOKEN`, `STT_HINTS_PATH`(위치별 사전 26곳), `TRANSLATE_PROVIDER=aws`, `ALLOW_TEXT_INPUT=0`, `PUBLIC_BASE_URL=https://<CloudFront 주소>`.
- EC2에는 Bedrock(Titan)·Translate(·Transcribe 대안) 권한 IAM 역할을 붙이고 AWS 키 두 개는 비움. `OPENAI_API_KEY`는 `.env`(또는 Secrets Manager)에만.
