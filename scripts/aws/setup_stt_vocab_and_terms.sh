#!/usr/bin/env bash
# 라이브 자막 품질용 AWS 리소스 만들기 (이슈 #3)
#   (a) 위치별 사전 → Amazon Transcribe 사용자 지정 어휘 (ko-KR), POI 마다 하나
#       이름 = PREFIX + poiId (':' → '-')  예: gunggeum-place-gyeonghoeru-pavilion  (api/app/live/stt.py 와 같은 규칙)
#   (b) 궁궐 용어 CSV → Amazon Translate 용어집 (이름 gunggeum-palace, OVERWRITE)
#
# 리포 없이 AWS CloudShell 에서도 돌아감 (aws CLI + python3 만 씀):
#   1) CloudShell 오른쪽 위 Actions → Upload file 로 이 스크립트, 힌트 JSON, 용어집 CSV 를 올림
#   2) bash setup_stt_vocab_and_terms.sh <힌트.json> <용어집.csv>
# 리포 안에서는 인자 없이: 기본값 api/data/stt_hints.json(없으면 example) · api/data/translate_terminology.csv
#
# 환경 변수: AWS_REGION(기본 ap-northeast-2) · VOCAB_PREFIX(기본 gunggeum-) · TERMINOLOGY_NAME(기본 gunggeum-palace)
#           WAIT=1 이면 어휘가 READY/FAILED 될 때까지 기다림
# 필요한 권한: transcribe:CreateVocabulary·UpdateVocabulary·GetVocabulary, translate:ImportTerminology
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." 2>/dev/null && pwd || echo .)"
default_hints="$root/api/data/stt_hints.json"
[ -f "$default_hints" ] || default_hints="$root/api/data/stt_hints.example.json"
hints="${1:-$default_hints}"
terms_csv="${2:-$root/api/data/translate_terminology.csv}"
region="${AWS_REGION:-ap-northeast-2}"
prefix="${VOCAB_PREFIX:-gunggeum-}"
terminology="${TERMINOLOGY_NAME:-gunggeum-palace}"

[ -f "$hints" ] || { echo "힌트 파일이 없음: $hints" >&2; exit 1; }
[ -f "$terms_csv" ] || { echo "용어집 CSV 가 없음: $terms_csv" >&2; exit 1; }
echo "region=$region prefix=$prefix hints=$hints terms=$terms_csv"

# 힌트 JSON → "어휘이름<TAB>phrase1 phrase2 ..." 줄. Transcribe 규칙에 맞춤:
#   어휘 이름 [0-9A-Za-z._-] 200자 이하 · phrase 안 공백은 '-' 로 · 한글/영문/'-'/'.'/'''만 남김 · 256자 이하 · 중복 제거
lines="$(PYTHONIOENCODING=utf-8 python3 - "$hints" "$prefix" <<'PY'
import json, re, sys
path, prefix = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding='utf-8'))
for poi, words in data.items():
    if str(poi).startswith('_') or not words:
        continue
    name = re.sub(r'[^0-9A-Za-z._-]', '-', prefix + str(poi).replace(':', '-'))[:200]
    phrases = []
    for w in words:
        p = re.sub(r'\s+', '-', str(w).strip())
        p = re.sub(r"[^가-힣A-Za-z.'-]", '', p).strip('-')
        if len(p.replace('-', '')) >= 1 and len(p) <= 256 and p not in phrases:
            phrases.append(p)
    if phrases:
        print(name + '\t' + ' '.join(phrases))
PY
)"

[ -n "$lines" ] || { echo "힌트 파일에 어휘로 만들 위치가 없음" >&2; exit 1; }

names=()
while IFS=$'\t' read -r name phrases; do
  # shellcheck disable=SC2086
  if aws transcribe get-vocabulary --region "$region" --vocabulary-name "$name" >/dev/null 2>&1; then
    aws transcribe update-vocabulary --region "$region" --vocabulary-name "$name" --language-code ko-KR \
      --phrases $phrases >/dev/null
    echo "어휘 업데이트: $name ($(wc -w <<<"$phrases")개)"
  else
    aws transcribe create-vocabulary --region "$region" --vocabulary-name "$name" --language-code ko-KR \
      --phrases $phrases >/dev/null
    echo "어휘 생성: $name ($(wc -w <<<"$phrases")개)"
  fi
  names+=("$name")
done <<<"$lines"

if [ "${WAIT:-0}" = 1 ]; then
  for name in "${names[@]}"; do
    for _ in $(seq 1 60); do
      state="$(aws transcribe get-vocabulary --region "$region" --vocabulary-name "$name" --query VocabularyState --output text)"
      [ "$state" = PENDING ] || break
      sleep 5
    done
    reason="$(aws transcribe get-vocabulary --region "$region" --vocabulary-name "$name" --query FailureReason --output text)"
    echo "$name: $state ${reason/None/}"
  done
fi

aws translate import-terminology --region "$region" --name "$terminology" --merge-strategy OVERWRITE \
  --description "경복궁 전각명·궁궐 용어 (gunggeum-be api/data/translate_terminology.csv)" \
  --terminology-data "Format=CSV,Directionality=UNI,File=fileb://$terms_csv" \
  --query 'TerminologyProperties.[Name,TermCount,SourceLanguageCode]' --output text

cat <<EOF

완료. 서버 .env 에 아래를 넣고 컨테이너를 다시 만들 것 (docker compose up -d):
  TRANSCRIBE_VOCABULARY_PREFIX=$prefix
  TRANSLATE_TERMINOLOGY=$terminology
어휘는 만든 뒤 몇 분간 PENDING 이라, 그동안은 서버가 어휘 없이 받아씀 (WAIT=1 로 상태 확인 가능).
EOF
