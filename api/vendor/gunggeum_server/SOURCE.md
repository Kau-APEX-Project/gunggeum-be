# 출처

이 폴더는 팀 저장소의 서버 로직을 **수정 없이** 복사한 것입니다. API 서버(`app/`)는 여기 있는 함수를 HTTP로 감싸기만 합니다.

| 항목 | 값 |
|---|---|
| 저장소 | `Kau-APEX-Project/gunggeum-ai-llm-gps` |
| 경로 | `server/` (+ `db/` → 이 리포의 `db/`) |
| 커밋 | `fd98149bf145124f0c48f051989ece6c8d393e22` (2026-11-16, PR #4 `fix/ask-here` 브랜치 끝 — 머지 전. 머지되면 머지 커밋으로 갱신) |
| 이전 | `Kau-APEX-Project/gunggeum` `deploy/server/` `0c7d687` (2026-10-23) |
| 담당 | 박윤서 (로직), 김병진 (HTTP 서버) |

## 규칙
- `aliases.json`(외국어 카드 링크 별칭)도 꼭 복사. 빠지면 오류 없이 외국어 답변의 카드 링크만 줄어듦.
- 이 폴더 파일은 여기서 고치지 않습니다. 로직 수정은 원래 저장소에서 하고, 새 커밋을 다시 복사한 뒤 위 커밋 해시를 갱신합니다.
- `course.py`의 `serve()`(localhost:8001 임시 서버)는 쓰지 않습니다. 정식 서버는 `app/`입니다.
- `config.py`는 `../.env`를 찾지만, 컨테이너에서는 환경 변수로 키를 넣으므로 파일이 없어도 됩니다.

## 다시 복사하기
```bash
cp <gunggeum-ai-llm-gps>/server/{ask.py,bedrock.py,cards.py,config.py,course.py,course-input.json,pg.py,requirements.txt,aliases.json} api/vendor/gunggeum_server/
cp <gunggeum-ai-llm-gps>/db/{00-vector.sql,docs.sql.gz} db/
```
