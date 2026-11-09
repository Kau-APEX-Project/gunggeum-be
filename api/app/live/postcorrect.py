"""후처리 사전 (STT 벤치마크 v2 2.4 · 3.5): 받아쓴 단어가 사전 단어와 비슷하면 사전 단어로 바꿈.

규칙 (보고서 그대로):
  - 유사도 = 자모 단위(초성·중성·종성으로 쪼갬) Jaro-Winkler, threshold 0.85
  - 어절 끝 조사·어미를 떼려고 어절 앞부분(사전 단어와 같은 음절 수)만 비교하고 그 부분만 바꿈 ("홍해문을" → "홍예문을")
  - 1음절 용어는 쓰지 않음. 여러 어절 용어는 어절마다 모두 threshold 이상이어야 바꿈
  - threshold 이상인 사전 단어 중 가장 비슷한 것으로 바꿈
  - 사전은 위치별 (전체 사전은 잘못 바꾸는 경우가 크게 늘어남)
쓰는 곳: 받아쓰기 사전이 없거나 약한 엔진(Amazon Transcribe 등). Whisper·Qwen3-ASR·CLOVA 처럼 받아쓰기 사전을 넣은 엔진에는
더하지 않음 (보고서 4.1). AI 담당 postcorrect.py 와 같은 규칙으로 다시 짠 것이라, 같은 입력으로 결과를 대조해 볼 것.
"""
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from app.settings import env

log = logging.getLogger('gunggeum.stt')

THRESHOLD = 0.85
_JONG_EMPTY = 0
HANGUL = re.compile('[가-힣]')


def jamo(text: str) -> str:
    """한글 음절 → 초성·중성·종성 문자열 (종성 없으면 생략). 한글이 아니면 그대로"""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            cho, jung, jong = code // 588, (code % 588) // 28, code % 28
            out.append(chr(0x1100 + cho) + chr(0x1161 + jung) + (chr(0x11A7 + jong) if jong != _JONG_EMPTY else ''))
        else:
            out.append(ch)
    return ''.join(out)


def jaro_winkler(a: str, b: str, p: float = 0.1) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    window = max(len(a), len(b)) // 2 - 1
    a_hit, b_hit = [False] * len(a), [False] * len(b)
    matches = 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - window), min(len(b), i + window + 1)):
            if not b_hit[j] and b[j] == ch:
                a_hit[i] = b_hit[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    a_m = [ch for ch, hit in zip(a, a_hit) if hit]
    b_m = [ch for ch, hit in zip(b, b_hit) if hit]
    transpositions = sum(x != y for x, y in zip(a_m, b_m)) / 2
    jaro = (matches / len(a) + matches / len(b) + (matches - transpositions) / matches) / 3
    prefix = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        prefix += 1
    return jaro + prefix * p * (1 - jaro)


def similarity(a: str, b: str) -> float:
    return jaro_winkler(jamo(a), jamo(b))


def correct(text: str, terms: list[str], threshold: float = THRESHOLD) -> str:
    """text 의 어절을 위치별 사전 terms 로 바로잡음"""
    vocab = [(t, t.split()) for t in dict.fromkeys(terms) if len(t.replace(' ', '')) > 1]  # 1음절 용어 제외
    if not vocab:
        return text
    tokens = text.split(' ')
    i = 0
    while i < len(tokens):
        best = None  # (점수, 용어, 어절 수)
        for term, parts in vocab:
            n = len(parts)
            window = tokens[i:i + n]
            if len(window) < n:
                continue
            scores = []
            for k, (tok, part) in enumerate(zip(window, parts)):
                # 마지막 어절은 앞부분만 비교 (뒤에 붙은 조사·어미 제외), 앞 어절은 통째로
                head = tok[:len(part)] if k == n - 1 else tok
                if len(head) < len(part) or not HANGUL.match(head):
                    break
                scores.append(similarity(head, part))
            if len(scores) < n or min(scores) < threshold:
                continue
            score = sum(scores) / n
            if best is None or (score, len(term)) > (best[0], len(best[1])):
                best = (score, term, n)
        if best:
            _, term, n = best
            parts = term.split()
            last = tokens[i + n - 1]
            tail = last[len(parts[-1]):]
            replaced = ' '.join(parts) + tail
            if ' '.join(tokens[i:i + n]) != replaced:
                tokens[i:i + n] = replaced.split(' ')
            i += n
        else:
            i += 1
    return ' '.join(tokens)


# ── 자주 틀리는 표기 → 정답 (정확 일치 표, 위치 무관) ──
# 유사도로 못 잡는 오인식용 (예: '경위로' vs '경회루' 는 자모 Jaro-Winkler 0.80 < 0.85).
# 파일: STT_CORRECTIONS_PATH (기본 api/data/stt_corrections.json), 형식 {"경위로": "경회루", ...}. "_" 로 시작하는 키는 주석.
# 어절 앞부분이 표기와 같으면 그 부분만 바꾸고 뒤에 붙은 조사·어미는 그대로 ("경위로는" → "경회루는"). 긴 표기부터 맞춤.
DEFAULT_CORRECTIONS = Path(__file__).resolve().parents[2] / 'data' / 'stt_corrections.json'


@lru_cache(maxsize=4)
def _load_corrections(path: str) -> tuple[tuple[str, str], ...]:
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        pairs = {str(k).strip(): str(v).strip() for k, v in data.items() if not str(k).startswith('_')}
    except (OSError, ValueError, AttributeError):
        log.exception('자주 틀리는 표기 표를 읽지 못함: %s (표 없이 진행)', path)
        return ()
    return tuple(sorted(((k, v) for k, v in pairs.items() if k and v and ' ' not in k), key=lambda kv: -len(kv[0])))


def corrections() -> tuple[tuple[str, str], ...]:
    return _load_corrections(env('STT_CORRECTIONS_PATH') or str(DEFAULT_CORRECTIONS))


def apply_corrections(text: str, table: tuple[tuple[str, str], ...] | None = None) -> str:
    table = corrections() if table is None else table
    if not table:
        return text
    tokens = text.split(' ')
    for i, tok in enumerate(tokens):
        for wrong, right in table:
            if tok.startswith(wrong):
                tokens[i] = right + tok[len(wrong):]
                break
    return ' '.join(tokens)
