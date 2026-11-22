"""자막 번역. TRANSLATE_PROVIDER=aws (Amazon Translate, 기본) | echo (개발용: 한국어 그대로)"""
import asyncio
import csv
import html
import logging
import re
from functools import lru_cache
from pathlib import Path

from app.settings import env

log = logging.getLogger('gunggeum.translate')
DEFAULT_TERMS = Path(__file__).resolve().parents[2] / 'data' / 'translate_terms.csv'
PIECE = re.compile(r'([0-9A-Za-z가-힣]+)')  # 글자 덩어리 (그 사이는 공백·줄바꿈·문장부호). 이슈 #16 1번
# 1글자 용어('왕')는 뒤가 조사이거나 어절이 거기서 끝날 때만 맞음 → '왕이'·'왕의' 는 바꾸고 '왕실'·'왕권'·'왕대비' 는 그대로
# (cornch-k 리뷰 2026-11-10: 300문장에서 앞부분만 맞추면 틀리는 곳 12, 맞는 곳 2)
PARTICLES = ('이', '가', '은', '는', '을', '를', '의', '와', '과', '도', '만', '에', '에서', '에게', '께', '께서',
             '로', '으로', '이나', '나', '까지', '부터', '보다', '처럼', '이다', '입니다', '이었', '였')
WORD = re.compile(r'[0-9A-Za-z가-힣]*')  # 용어 바로 뒤에 이어지는 글자 (문장부호 앞까지)
# 공지 번역만: 용어 바로 뒤가 하다·되다 활용형이면 동사로 보고 감싸지 않음 ('대비해', '조정됩니다'). 이슈 #16 2번
# 자막은 '승하했습니다' 처럼 어려운 한자어 동사가 많아 감싸지 않으면 오역됨(승하 → won) → 자막엔 안 씀
VERB = re.compile(r'(하|했|한|할|함|합|해|되|됐|된|될|됨|됩|돼)')
# 공지 번역만: 일반 낱말과 글자가 같은 용어는 감싸지 않음 ('폭염 대비', '담당자 부재', '조회 수'). 이슈 #16 2번
# (전각·장소 이름만 고정하는 안은 용어집에 분류 열이 없어, 공지 예문에서 문제가 된 낱말만 뺌)
NOTICE_PLAIN_WORDS = frozenset({'대비', '부재', '조회'})


@lru_cache(maxsize=4)
def _load_glossary(path: str) -> dict[str, dict[str, str]]:
    """용어집 CSV (ko,en,th) → {한국어 용어: {언어: 표기}}. 띄어쓰기 있는 용어는 뺌. 1글자 용어는 _each_term 이 조사 앞에서만 맞춤"""
    try:
        with open(path, encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f))
    except OSError:
        log.warning('용어집 CSV 를 읽지 못함: %s (용어 처리 없이 번역)', path)
        return {}
    out = {}
    for r in rows:
        ko = (r.get('ko') or '').strip()
        if ko and ' ' not in ko:
            out[ko] = {k: (v or '').strip() for k, v in r.items() if k and k != 'ko'}
    return out


def glossary() -> dict[str, dict[str, str]]:
    return _load_glossary(env('TRANSLATE_TERMS_PATH') or str(DEFAULT_TERMS))


def roman_name(en: str) -> str:
    """영어 카드 표기의 괄호 앞 이름: 'Geunjeongjeon (Throne Hall)' → 'Geunjeongjeon'"""
    return re.sub(r'\s*\(.*$', '', en or '').strip()


def is_bundle(en: str) -> bool:
    """여러 용어를 한 줄로 묶은 표기 ('Changgeon / Junggeon / …', 'Gukbo and Bomul (…)').
    자막에 그대로 넣으면 '복원했습니다' 가 묶음 전체로 나와서 바꿔 넣지 않음 (안기겸 검토 2026-11-10: 영문 이름에 / 나 and)"""
    name = roman_name(en)
    return '/' in name or bool(re.search(r'\band\b', name))


def term_table(lang: str, table: dict[str, dict[str, str]]) -> list[str]:
    """그 언어 표기가 있고 묶음 표기가 아닌 한국어 용어, 긴 것부터"""
    return sorted((k for k, v in table.items() if v.get(lang) and not is_bundle(v.get('en', ''))), key=len, reverse=True)


def glossary_terms() -> tuple[str, ...]:
    """한국어 용어, 긴 것부터 ('근정전' 이 '정전' 보다 먼저 맞게)"""
    return tuple(sorted(glossary(), key=len, reverse=True))


def _fits(body: str, term: str) -> bool:
    """어절 body 가 용어로 시작하는지. 2글자 이상은 뒤에 무엇이 붙어도 되고, 1글자는 뒤가 조사이거나 비어 있을 때만"""
    if not body.startswith(term):
        return False
    if len(term) > 1:
        return True
    rest = WORD.match(body, 1).group()  # '왕이.' → '이', '왕"은' → ''
    return rest == '' or rest in PARTICLES


def _each_term(text: str, terms):
    """글자 덩어리마다 (앞 공백·문장부호, 맞은 용어 또는 None, 나머지). 용어는 덩어리 시작에서만, 뒤에는 조사·어미가 붙어도 됨.
    공백뿐 아니라 줄바꿈·가운뎃점·괄호 뒤에서도 용어를 찾음 ('…합니다.\n근정전·경회루 일대는'). 이어 붙이면 원문 그대로 (이슈 #16 1번)"""
    parts = PIECE.split(text)  # [사이0, 덩어리1, 사이1, 덩어리2, …, 사이N]
    for i in range(1, len(parts), 2):
        body = parts[i]
        term = next((t for t in terms if _fits(body, t)), None)
        yield parts[i - 1], term, body[len(term):] if term else body
    yield parts[-1], None, ''  # 마지막 덩어리 뒤에 남은 문장부호·공백


def split_particles(text: str, terms: tuple[str, ...]) -> str:
    """TRANSLATE_TERM_MODE=terminology 용. Amazon Translate 용어집은 단어 단위로만 맞춤 → 조사가 붙으면('근정전은') 적용 안 됨.
    용어 뒤를 띄움: '근정전은' → '근정전 은'. (서버 시험: 띄워도 영어는 일부만, 태국어는 0개 적용 → 기본은 substitute)"""
    if not terms:
        return text
    return ''.join(head + (term + (' ' + rest if rest else '') if term else rest)
                    for head, term, rest in _each_term(text, terms))


def substitute_terms(text: str, lang: str, table: dict[str, dict[str, str]]) -> str:
    """TRANSLATE_TERM_MODE=substitute (기본). 번역 전에 한국어 용어를 그 언어의 카드 표기로 바꿔 넣음
    ('근정전은' → 'Geunjeongjeon (Throne Hall)은'). Translate 가 이미 외국어인 부분은 그대로 두므로 표기가 카드와 같게 고정됨
    → 자막 카드 링크(cards.link_names)가 맞음. 그 언어 표기가 비어 있는 용어는 바꾸지 않음 (2026-11-10 서버 비교 시험)"""
    if not table:
        return text
    terms = term_table(lang, table)
    return ''.join(head + (table[term][lang] + rest if term else rest) for head, term, rest in _each_term(text, terms))


def placeholder_terms(text: str, lang: str, table: dict[str, dict[str, str]], style: str = 'token') -> tuple[str, dict[str, str]]:
    """영어 외 자막(태국어 등)용. 원문이 한국어라 태국 문자를 넣으면 Translate 가 지워 버리므로 (2026-11-10 서버 시험)
    용어를 라틴 자리표시자로 바꿔 번역하고, 번역 뒤 restore_terms 로 그 언어 표기로 되돌림.
      token  고유 토큰 GGT0, GGT1, … (기본. 번역 뒤에도 그대로 남음)
      roman  용어집 en 표기의 괄호 앞 로마자 이름 ('Geunjeongjeon') — 태국어로 음역돼 되돌리지 못하는 경우가 있음
    그 언어 표기가 빈 용어는 그대로 둠. 돌려주는 표: {자리표시자: 그 언어 표기}"""
    if not table:
        return text, {}
    terms = term_table(lang, table)
    marks: dict[str, str] = {}
    by_term: dict[str, str] = {}
    out = []
    for head, term, rest in _each_term(text, terms):
        if term:
            if term not in by_term:
                roman = roman_name(table[term].get('en'))
                mark = roman if style == 'roman' and roman and roman not in marks else f'GGT{len(marks)}'
                by_term[term] = mark
                marks[mark] = table[term][lang]
            out.append(head + by_term[term] + rest)
        else:
            out.append(head + rest)
    return ''.join(out), marks


def restore_terms(text: str, marks: dict[str, str]) -> str:
    """번역문의 자리표시자를 그 언어 표기로 (긴 것부터, 영문자에 붙은 것은 안 바꿈: Geunjeongjeon 속 Jeongjeon)"""
    for mark in sorted(marks, key=len, reverse=True):
        text = re.sub(rf'(?<![A-Za-z]){re.escape(mark)}(?![A-Za-z])', lambda _m, v=marks[mark]: v, text, flags=re.I)
    return text


NO_TRANSLATE = re.compile(r'<span\s+translate\s*=\s*["\']no["\']\s*>\s*(.*?)\s*</span>', re.I | re.S)


def _paren_inner(items) -> set[int]:
    """용어 바로 뒤 괄호 안에 용어 하나만 있는 곳('사정전(편전)')의 안쪽 덩어리 번호.
    둘 다 카드 표기로 바꾸면 'Sajeongjeon (Royal Council Hall)(Pyeonjeon (Royal Council Hall))' 처럼 괄호가 겹침.
    괄호 안에 다른 말이 함께 있으면('근정전 월대(근정전 앞 계단 구역)') 해당 없음 (안기겸 리뷰 2026-11-22)"""
    out = set()
    for i in range(1, len(items)):
        head, term, rest = items[i]
        _, before, before_rest = items[i - 1]
        nxt = items[i + 1][0] if i + 1 < len(items) else ''
        if term and not rest and before and not before_rest and head.strip() == '(' and nxt.startswith(')'):
            out.add(i)
    return out


def notice_terms(terms: list[str]) -> list[str]:
    """공지 번역에서 감쌀 용어 (일반 낱말과 같은 용어 뺌)"""
    return [t for t in terms if t not in NOTICE_PLAIN_WORDS]


def wrap_terms(text: str, lang: str, table: dict[str, dict[str, str]], notice: bool = False) -> tuple[str, dict[str, str]]:
    """TRANSLATE_TERM_MODE=notranslate (기본). 용어를 로마자 이름만 넣고 번역 제외 표시로 감쌈
    ('근정전은' → '<span translate="no">Geunjeongjeon</span>은'). Translate 는 감싼 부분을 건드리지 않음.
    번역 뒤 unwrap_terms 가 그 언어 카드 표기로 바꿈 → 영어·태국어가 같은 방식, 카드 링크도 맞음.
    안기겸 검토(2026-11-10, 300문장 772항목): 괄호 설명까지 넣기 84.1%, 이름만 넣고 뒤에 붙이기 94.2%, 번역 제외 표시 99.2%.
    로마자 이름이 없거나 다른 용어와 겹치면 GGT 토큰. 돌려주는 표: {감싼 글자: 그 언어 표기}
    notice=True (공지): 일반 낱말과 같은 용어(NOTICE_PLAIN_WORDS)와 동사로 쓰인 용어('조정됩니다')는 감싸지 않음"""
    if not table:
        return text, {}
    terms = term_table(lang, table)
    if notice:
        terms = notice_terms(terms)
    items = list(_each_term(text, terms))
    inner = _paren_inner(items)
    normal = {t for i, (_, t, _) in enumerate(items) if t and i not in inner}
    marks: dict[str, str] = {}
    by_term: dict[str, str] = {}
    out = []
    for i, (head, term, rest) in enumerate(items):
        if term and notice and VERB.match(rest):  # 동사로 쓰인 용어('대비해', '조정됩니다')는 그대로
            out.append(head + term + rest)
            continue
        if term and i in inner:  # '사정전(편전)' 의 편전 → 괄호 안은 그 언어 이름만 ('(Pyeonjeon)'), 바깥 괄호와 띄움
            label = roman_name(table[term][lang]) or table[term][lang]
            name = roman_name(table[term].get('en'))
            mark = name if name and name not in marks and term not in normal else f'GGT{len(marks)}'
            marks[mark] = label
            out.append(f'{" (" if head == "(" else head}<span translate="no">{mark}</span>{rest}')
            continue
        if term:
            if term not in by_term:
                name = roman_name(table[term].get('en'))
                mark = name if name and name not in marks else f'GGT{len(marks)}'
                by_term[term] = mark
                marks[mark] = table[term][lang]
            out.append(f'{head}<span translate="no">{by_term[term]}</span>{rest}')
        else:
            out.append(head + rest)
    return ''.join(out), marks


def unwrap_terms(text: str, marks: dict[str, str]) -> str:
    """번역문의 번역 제외 표시를 그 언어 카드 표기로 바꾸고 HTML 문자(&amp; 등)를 되돌림.
    Translate 가 표시를 없앴으면 남은 이름·토큰을 restore_terms 로 바꿈"""
    first = NO_TRANSLATE.search(text)
    if first:
        at_start = not re.search(r'[0-9A-Za-z\u0E00-\u0E7F가-힣]', text[:first.start()])

        def put(m):
            value = marks.get(m.group(1), m.group(1))
            if at_start and m.start() == first.start() and value[:1].islower():  # 문장 첫머리 일반 단어('the queen') → 대문자
                value = value[0].upper() + value[1:]
            return value
        text = NO_TRANSLATE.sub(put, text)
        text = re.sub(r'\b([Tt]he) the\b', r'\1', text)  # Translate 가 'the' 를 붙인 뒤 'the queen' 이 들어간 경우
    else:
        text = restore_terms(text, marks)
    return html.unescape(text)


# ---------- 연도 보호 (자막·공지 공통, 이슈 #16 7·8번) ----------
# 태국어 번역에서 'NNNN년' 이 'ในปี ค.' 로 잘려 연도가 사라짐 (해설 연도 문장 77개 중 11개) → 숫자만 번역 제외 표시로 감쌈
YEAR = re.compile(r'(?<!\d)(\d{4})년')
YEAR_MARK = re.compile(r'(\s?)[\'‘’"]?<span\s+translate\s*=\s*["\']no["\']\s*>\s*(\d{4})\s*</span>[\'‘’"]?', re.I)
TH_MONTHS = ('มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน', 'กรกฎาคม', 'สิงหาคม',
             'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม')
FOUR_DIGITS = re.compile(r'(?<!\d)(\d{4})(?!\d)')


def wrap_years(text: str) -> str:
    """'1985년' → '<span translate="no">1985</span>년' ('년' 은 남겨 번역기가 연도로 알아보게)"""
    return YEAR.sub(r'<span translate="no">\1</span>년', text)


def put_years(text: str, lang: str) -> str:
    """연도 표시를 풀면서 앞뒤 따옴표를 떼고('2018' → 2018), 태국어는 앞에 'ปี' 가 없으면 넣음
    (날짜·달 이름 뒤, ปี·ปีที่·ค.ศ.·พ.ศ. 뒤, 숫자 뒤는 그대로)"""
    def one(m):
        space, y = m.group(1), m.group(2)
        if lang != 'th':
            return space + y
        before = text[:m.start()].rstrip()
        if before.endswith(('ปี', 'ปีที่', 'ค.ศ.', 'พ.ศ.') + TH_MONTHS) or re.search(r'\d$', before):
            return space + y
        glue = bool(re.search(r'[\u0E00-\u0E7F]$', before))
        return ('' if glue else space) + 'ปี ' + y
    return YEAR_MARK.sub(one, text)


def extra_years(src: str, out: str, marks: dict[str, str]) -> bool:
    """번역문에 원문·용어 표기에 없는 4자리 숫자가 생겼는지 (번역 제외 표시가 많은 문장에서 번역기가 연도를 지어냄:
    '소주방은 … 2015년에 복원' → 1967). 용어 표기 속 연도(임진왜란 1592–1598, 광복 1945)는 허용"""
    allowed = set(FOUR_DIGITS.findall(src)) | {y for v in marks.values() for y in FOUR_DIGITS.findall(v)}
    return bool(set(FOUR_DIGITS.findall(out)) - allowed)


# ---------- 공지만 하는 전처리 (이슈 #16 3·4·5번) ----------
DOT_DATE = re.compile(r'(?<!\d)(\d{4})\.\s?(\d{1,2})\.\s?(\d{1,2})(?!\d)\.?')
RANGE_END = re.compile(r'([~∼〜]\s*)(\d{1,2})\.\s?(\d{1,2})(?![\d:])\.?')  # 기간 끝 'M. D.' (연도 없음)
ANGLE = re.compile(r'<([^<>\n]+)>')
SQUARE = re.compile(r'\[([^\[\]\n]+)\]')


def korean_dates(text: str) -> str:
    """'2026. 12. 1.(화)' → '2026년 12월 1일(화)'. 점 찍는 날짜에서 번역기가 문장을 나누는 것을 막음.
    기간의 ~ 뒤에 연도 없이 오는 날짜도 바꿈: '2026. 12. 8.(화) ~ 12. 19.(토)' → '… ~ 12월 19일(토)' (안기겸 리뷰 N25)"""
    def ok(mo, d):
        return 1 <= int(mo) <= 12 and 1 <= int(d) <= 31

    def one(m):
        y, mo, d = m.groups()
        return f'{y}년 {int(mo)}월 {int(d)}일' if ok(mo, d) else m.group()

    def tail(m):
        sep, mo, d = m.groups()
        return f'{sep}{int(mo)}월 {int(d)}일' if ok(mo, d) else m.group()
    return RANGE_END.sub(tail, DOT_DATE.sub(one, text))


def hide_angles(text: str) -> tuple[str, bool]:
    """'<긴급>' 은 번역기가 HTML 태그로 보고 한글 그대로 남김 → '[긴급]' 으로 보내고 show_angles 로 되돌림.
    원문에 대괄호가 이미 있으면 되돌릴 때 헷갈리므로 그대로 둠"""
    if '[' in text or ']' in text or not ANGLE.search(text):
        return text, False
    return ANGLE.sub(r'[\1]', text), True


def show_angles(text: str) -> str:
    return SQUARE.sub(lambda m: f'<{m.group(1).strip()}>', text)


def add_ui(text: str, terms) -> str:
    """줄 첫머리 낱말이 용어 하나이고 바로 뒤가 띄어쓰기면 '의' 를 넣음 ('광화문 야간 조명' → '광화문의 야간 조명').
    번역 제외 표시로 감싼 용어 뒤에 조사 없이 명사가 오면 번역기가 용어를 문장과 따로 다룸. 공지에서만"""
    terms = set(terms)
    lines = []
    for line in text.split('\n'):
        head, sep, rest = line.partition(' ')
        lines.append(f'{head}의 {rest}' if sep and rest and head in terms else line)
    return '\n'.join(lines)


class EchoTranslator:
    """키 없이 흐름만 확인할 때. 번역하지 않고 한국어를 그대로 돌려줌"""

    async def translate(self, text: str, lang: str, notice: bool = False) -> str:
        return text


def is_missing_terminology(e: Exception) -> bool:
    """용어집 이름이 AWS 에 없음 (botocore ClientError 의 오류 코드로 판단)"""
    return getattr(e, 'response', {}).get('Error', {}).get('Code') == 'ResourceNotFoundException'


class AwsTranslator:
    """Amazon Translate. 전각명·궁궐 용어 표기 고정 방식 TRANSLATE_TERM_MODE:
      notranslate (기본) 로마자 이름을 번역 제외 표시로 감싸 번역한 뒤 그 언어의 카드 표기로 바꿈 (모든 언어 같은 방식)
      substitute         번역 전에 용어를 그 언어의 카드 표기로 바꿔 넣고 용어집 없이 번역
      terminology        Custom Terminology (TRANSLATE_TERMINOLOGY=이름) + 용어 뒤 조사 띄우기
    용어집은 요청 하나에 하나만 받으므로 여러 개를 적으면 첫 번째만 씀.
    용어집이 없으면(ResourceNotFound) 용어집 없이 다시 번역해 자막이 빠지지 않게 하고, 그 뒤로는 용어집을 빼고 부름."""

    def __init__(self, client=None):
        if client is None:
            import boto3
            client = boto3.client('translate', region_name=env('AWS_REGION', 'ap-northeast-2'))
        self.client = client
        names = [t.strip() for t in env('TRANSLATE_TERMINOLOGY').split(',') if t.strip()]
        if len(names) > 1:
            log.warning('TRANSLATE_TERMINOLOGY 는 하나만 쓸 수 있어 첫 번째(%s)만 씀', names[0])
        self.terminology: str | None = names[0] if names else None
        self.mode = env('TRANSLATE_TERM_MODE', 'notranslate').strip().lower() or 'notranslate'
        if self.mode not in ('notranslate', 'substitute', 'terminology'):
            log.warning('TRANSLATE_TERM_MODE=%s 는 모름 → notranslate', self.mode)
            self.mode = 'notranslate'
        # 카드 표기를 그대로 넣는 언어. 태국어는 원문에 태국 문자를 넣으면 Translate 가 지워 버림 ("() เป็น ()", 2026-11-10 서버 시험)
        self.substitute_langs = {x.strip() for x in env('TRANSLATE_SUBSTITUTE_LANGS', 'en').split(',') if x.strip()}
        # 그 밖의 언어는 자리표시자로 번역한 뒤 되돌림: token (기본) | roman
        # 서버 시험(2026-11-10, th): roman 은 Translate 가 로마자 이름을 태국 문자로 음역해 버려 되돌릴 수 없었고, GGT 토큰은 그대로 남음
        self.placeholder = env('TRANSLATE_PLACEHOLDER', 'token').strip().lower() or 'token'

    async def _call(self, text: str, lang: str, terminology: str | None) -> str:
        extra = {}
        if terminology:
            extra = {'TerminologyNames': [terminology]}
            text = split_particles(text, glossary_terms())
        res = await asyncio.to_thread(self.client.translate_text, Text=text, SourceLanguageCode='ko',
                                      TargetLanguageCode=lang, **extra)
        return res['TranslatedText']

    async def translate(self, text: str, lang: str, notice: bool = False) -> str:
        """notice=True 는 공지 번역 (POST /api/admin/notices translate:true): 점 날짜·꺾쇠 머리말·줄 첫머리 용어·동사 용어 처리를 더함"""
        if not notice:
            return await self._translate(text, lang, False)
        text, angled = hide_angles(korean_dates(text))
        out = await self._translate(text, lang, True)
        return show_angles(out) if angled else out

    async def _translate(self, text: str, lang: str, notice: bool) -> str:
        if self.mode == 'notranslate':
            table = glossary()
            if notice and table:
                text = add_ui(text, notice_terms(term_table(lang, table)))
            wrapped, marks = wrap_terms(text, lang, table, notice=notice)
            out = unwrap_terms(put_years(await self._call(wrap_years(wrapped), lang, None), lang), marks)
            if extra_years(text, out, marks):  # 번역기가 원문에 없는 연도를 지어냄 → 그 문장만 연도 보호 없이 다시
                out = unwrap_terms(await self._call(wrapped, lang, None), marks)
            return out
        if self.mode == 'substitute':
            if lang in self.substitute_langs:
                return await self._call(substitute_terms(text, lang, glossary()), lang, None)
            text, marks = placeholder_terms(text, lang, glossary(), self.placeholder)
            return restore_terms(await self._call(text, lang, None), marks)
        terminology = self.terminology
        if terminology:
            try:
                return await self._call(text, lang, terminology)
            except Exception as e:
                if not is_missing_terminology(e):
                    raise
                log.warning('용어집 %s 이 없어 용어집 없이 번역함 (이후로도 생략): %s', terminology, e)
                self.terminology = None
        return await self._call(text, lang, None)


def make_translator():
    return EchoTranslator() if env('TRANSLATE_PROVIDER', 'aws') == 'echo' else AwsTranslator()
