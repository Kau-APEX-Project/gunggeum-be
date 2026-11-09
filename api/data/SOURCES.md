# api/data 출처

| 파일 | 원본 | 만드는 법 |
|---|---|---|
| `translate_terms.csv` | `Kau-APEX-Project/gunggeum-ai-stt` `gunggeum_stt/data/translate_terms.csv` (커밋 `52c433c`, 2026-11-04). 전각 71곳·용어 231개 카드 이름 ko→en·th 329개. 원본 표기는 그 리포의 `경복궁_전각.xlsx`·`경복궁_용어.xlsx` | 원본 리포에서 `python -m gunggeum_stt.build_glossary` 로 만든 파일을 그대로 복사 (여기서 고치지 않음) |
| `stt_hints.json` | 같은 리포 `gunggeum_stt/data/hints_by_location.json` (37개 해설 위치) + `Kau-APEX-Project/gunggeum-ai-llm-gps` `visit/data/pois.json` (커밋 `c092daa`, 71곳) | `python scripts/convert_stt_hints.py <hints_by_location.json> <pois.json>` |
| `stt_hints.example.json` | 예시 2곳 (테스트·개발용) | 손으로 작성 |
| `stt_corrections.json` | 자주 틀리는 표기 → 정답 (AWS Transcribe 시험 2026-11-10) | 손으로 작성 |

용어집 CSV 를 AWS 에 등록: `scripts/aws/setup_stt_vocab_and_terms.sh` (이름 기본 `gungeum-ko`, 원본 리포 `python -m gunggeum_stt.glossary --create-terminology` 와 같은 이름·같은 내용).

## AWS 등록 상태 (서울 ap-northeast-2, 2026-11-09 CloudShell 확인)
- Transcribe 사용자 지정 어휘 72개 모두 READY: 공통 `gungeum-gyeongbokgung-ko` 1개 + 위치별 `gungeum-place-<poiId>` 71개 (`stt_hints.json` 의 POI 71곳과 이름이 정확히 대응)
- Translate 용어집 `gungeum-ko` 329개 (`translate_terms.csv` 와 같은 수)
- 이미 등록돼 있으므로 다시 만들 필요 없음. 단어를 바꿨을 때만 `SKIP_TERMS=1 WAIT=1 bash scripts/aws/setup_stt_vocab_and_terms.sh` (어휘만 갱신)
