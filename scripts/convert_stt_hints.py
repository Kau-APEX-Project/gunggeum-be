"""STT 위치별 사전 → BE 힌트 파일 (STT_HINTS_PATH) 변환.

입력
  hints : gunggeum-ai-stt  gunggeum_stt/data/hints_by_location.json   {"<해설 위치 이름>": ["용어", ...]}
  pois  : gunggeum-ai-llm-gps  visit/data/pois.json                   [{"id": "place:...", "name", "group"}, ...]
출력
  api/data/stt_hints.json  {"<poiId>": ["용어", ...]}  (api/app/live/hints.py 가 읽는 형식)

키 → POI 맞추기
  1. 묶음 키 '협길당·함화당·흥복전' 은 '·' 로 나눠 각각 맞춤
  2. 이름이 pois 의 name 과 같으면 그 POI
  3. 아니면 pois 의 group 과 같으면 그 group 의 POI 전부
  4. 아니면 첫 어절로 group 을 찾음 ('태원전 일곽' → group 태원전, '건청궁 부속' → group 건청궁)
  맞는 POI 가 없으면 건너뜀 (예: '기타'). 같은 POI 에 여러 키가 걸리면 용어를 합치고 중복은 뺌 (먼저 나온 순서 유지)

  python scripts/convert_stt_hints.py <hints_by_location.json> <pois.json> [출력 경로=api/data/stt_hints.json]
"""
import json
import sys
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[1] / 'api' / 'data' / 'stt_hints.json'


def match(key: str, pois: list[dict]) -> list[str]:
    by_name, by_group = {}, {}
    for p in pois:
        by_name.setdefault(p['name'], []).append(p['id'])
        if p.get('group'):
            by_group.setdefault(p['group'], []).append(p['id'])
    ids = []
    for part in (s.strip() for s in key.split('·')):
        found = by_name.get(part) or by_group.get(part) or by_group.get(part.split()[0] if part else '', [])
        ids += [i for i in found if i not in ids]
    return ids


def convert(hints: dict[str, list[str]], pois: list[dict]) -> tuple[dict[str, list[str]], list[str]]:
    out, skipped = {}, []
    for key, terms in hints.items():
        if key.startswith('_'):
            continue
        ids = match(key, pois)
        if not ids:
            skipped.append(key)
        for poi in ids:
            merged = out.setdefault(poi, [])
            merged += [t for t in terms if t not in merged]
    return out, skipped


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        sys.exit(__doc__)
    hints = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
    pois = json.loads(Path(argv[2]).read_text(encoding='utf-8'))
    out_path = Path(argv[3]) if len(argv) > 3 else DEFAULT_OUT
    out, skipped = convert(hints, pois)
    note = (f'gunggeum-ai-stt hints_by_location.json ({len(hints)}개 위치) → gunggeum-ai-llm-gps pois.json id. '
            f'scripts/convert_stt_hints.py 로 만듦 (손으로 고치지 말 것). 건너뜀: {", ".join(skipped) or "없음"}')
    out_path.write_text(json.dumps({'_note': note, **out}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{out_path}: POI {len(out)}곳, 건너뛴 키 {skipped}')


if __name__ == '__main__':
    main(sys.argv)
