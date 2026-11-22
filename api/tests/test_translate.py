"""Amazon Translate 용어집 처리 (이슈 #3)"""
import asyncio

import pytest

from app.live.translate import AwsTranslator


class NotFound(Exception):
    def __init__(self):
        super().__init__('ResourceNotFoundException: terminology not found')
        self.response = {'Error': {'Code': 'ResourceNotFoundException'}}


class FakeClient:
    def __init__(self, fail_with=None):
        self.calls, self.fail_with = [], fail_with

    def translate_text(self, **kw):
        self.calls.append(kw.get('TerminologyNames'))
        if kw.get('TerminologyNames') and self.fail_with:
            raise self.fail_with
        return {'TranslatedText': f"en:{kw['Text']}"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def terminology_mode(monkeypatch):
    """아래 용어집 테스트는 TRANSLATE_TERM_MODE=terminology 기준 (substitute 테스트는 따로 바꿈)"""
    monkeypatch.setenv('TRANSLATE_TERM_MODE', 'terminology')


def test_uses_only_first_terminology(monkeypatch):
    monkeypatch.setenv('TRANSLATE_TERMINOLOGY', 'gunggeum-palace, other')
    client = FakeClient()
    t = AwsTranslator(client)
    assert run(t.translate('근정전', 'en')) == 'en:근정전'
    assert client.calls == [['gunggeum-palace']]


def test_no_terminology(monkeypatch):
    monkeypatch.delenv('TRANSLATE_TERMINOLOGY', raising=False)
    client = FakeClient()
    run(AwsTranslator(client).translate('왕', 'en'))
    assert client.calls == [None]


def test_missing_terminology_retries_without_and_then_skips(monkeypatch):
    monkeypatch.setenv('TRANSLATE_TERMINOLOGY', 'gunggeum-palace')
    client = FakeClient(fail_with=NotFound())
    t = AwsTranslator(client)
    assert run(t.translate('정전', 'en')) == 'en:정전'   # 자막이 빠지지 않음
    assert run(t.translate('왕', 'en')) == 'en:왕'
    assert client.calls == [['gunggeum-palace'], None, None]  # 두 번째부터는 용어집 생략


def test_other_errors_still_raise(monkeypatch):
    monkeypatch.setenv('TRANSLATE_TERMINOLOGY', 'gunggeum-palace')
    t = AwsTranslator(FakeClient(fail_with=RuntimeError('throttled')))
    with pytest.raises(RuntimeError):
        run(t.translate('정전', 'en'))
    assert t.terminology == 'gunggeum-palace'


def test_shipped_terminology_csv_matches_card_names():
    import csv
    from pathlib import Path
    import app
    path = Path(app.__file__).resolve().parents[1] / 'data' / 'translate_terms.csv'
    rows = list(csv.reader(path.open(encoding='utf-8')))
    assert rows[0] == ['ko', 'en', 'th']
    terms = {r[0]: r[1] for r in rows[1:]}
    assert terms['근정전'] == 'Geunjeongjeon (Throne Hall)'  # 카드 name_en 과 같은 표기 (자막 카드 링크가 맞게)
    assert terms['정전'].startswith('Jeongjeon')


@pytest.mark.parametrize('ko, spaced', [
    ('근정전은 경복궁의 정전입니다.', '근정전 은 경복궁 의 정전 입니다.'),  # 서버 시험에서 용어집이 안 맞던 문장
    ('경회루는 왕이 연회를 열던 누각입니다', '경회루 는 왕이 연회를 열던 누각입니다'),
    ('근정전에서 경회루까지', '근정전 에서 경회루 까지'),
    ('근정전 앞', '근정전 앞'),          # 이미 떨어져 있으면 그대로
    ('오늘 날씨', '오늘 날씨'),
])
def test_split_particles(ko, spaced):
    from app.live.translate import split_particles
    terms = ('근정전', '경회루', '경복궁', '정전')  # 긴 것부터
    assert split_particles(ko, terms) == spaced
    assert split_particles('"근정전"은', terms) == '"근정전"은'  # 따옴표로 이미 떨어져 있으면 그대로 (이슈 #16 1번)


def test_glossary_terms_from_shipped_csv(monkeypatch):
    from app.live.translate import glossary_terms
    monkeypatch.delenv('TRANSLATE_TERMS_PATH', raising=False)
    terms = glossary_terms()
    assert '근정전' in terms and terms.index('근정전') < terms.index('정전')  # 긴 용어가 먼저


def test_split_only_with_terminology(monkeypatch):
    monkeypatch.delenv('TRANSLATE_TERMS_PATH', raising=False)
    sent = []

    class C:
        def translate_text(self, **kw):
            sent.append((kw['Text'], kw.get('TerminologyNames')))
            return {'TranslatedText': 'x'}
    monkeypatch.setenv('TRANSLATE_TERMINOLOGY', 'gungeum-ko')
    run(AwsTranslator(C()).translate('근정전은 정전입니다.', 'en'))
    monkeypatch.delenv('TRANSLATE_TERMINOLOGY')
    run(AwsTranslator(C()).translate('근정전은 정전입니다.', 'en'))
    assert sent == [('근정전 은 정전 입니다.', ['gungeum-ko']), ('근정전은 정전입니다.', None)]


TABLE = {'근정전': {'en': 'Geunjeongjeon (Throne Hall)', 'th': 'คึนจองจอน (ท้องพระโรง)'},
         '정전': {'en': 'Jeongjeon (main hall of a palace)', 'th': ''},
         '경회루': {'en': 'Gyeonghoeru (Banquet Pavilion)', 'th': 'คยองฮเวรู (พลับพลาจัดงานเลี้ยง)'}}


@pytest.mark.parametrize('ko, lang, out', [
    ('근정전은 경복궁의 정전입니다.', 'en', 'Geunjeongjeon (Throne Hall)은 경복궁의 Jeongjeon (main hall of a palace)입니다.'),
    ('근정전은 경복궁의 정전입니다.', 'th', 'คึนจองจอน (ท้องพระโรง)은 경복궁의 정전입니다.'),  # th 표기가 빈 용어는 그대로
    ('근정전에서 경회루까지', 'en', 'Geunjeongjeon (Throne Hall)에서 Gyeonghoeru (Banquet Pavilion)까지'),
    ('"경회루"는', 'en', '"Gyeonghoeru (Banquet Pavilion)"는'),
    ('대근정전 앞', 'en', '대근정전 앞'),  # 어절 중간은 안 바꿈
    ('근정전', 'ja', '근정전'),          # 없는 언어 열
])
def test_substitute_terms(ko, lang, out):
    from app.live.translate import substitute_terms
    assert substitute_terms(ko, lang, TABLE) == out


def test_substitute_mode_skips_terminology(monkeypatch):
    monkeypatch.setenv('TRANSLATE_TERM_MODE', 'substitute')
    monkeypatch.delenv('TRANSLATE_SUBSTITUTE_LANGS', raising=False)
    monkeypatch.delenv('TRANSLATE_TERMS_PATH', raising=False)
    monkeypatch.setenv('TRANSLATE_TERMINOLOGY', 'gungeum-ko')
    sent = []

    class C:
        def translate_text(self, **kw):
            sent.append((kw['Text'], kw.get('TerminologyNames')))
            return {'TranslatedText': kw['Text']}
    t = AwsTranslator(C())
    assert t.mode == 'substitute'
    run(t.translate('근정전은 경복궁의 정전입니다.', 'en'))
    th = run(t.translate('근정전은 경복궁의 정전입니다.', 'th'))  # 태국어는 GGT 토큰으로 보내고 되돌림
    assert sent == [('Geunjeongjeon (Throne Hall)은 Gyeongbokgung Palace의 Jeongjeon (main hall of a palace)입니다.', None),
                    ('GGT0은 경복궁의 GGT1입니다.', None)]  # 경복궁은 태국어 표기가 비어 있어 그대로
    assert th == 'คึนจองจอน (ท้องพระโรง)은 경복궁의 ชองจอน (ท้องพระโรงหลัก)입니다.'
    monkeypatch.setenv('TRANSLATE_SUBSTITUTE_LANGS', 'en,th')
    sent.clear()
    run(AwsTranslator(C()).translate('근정전은', 'th'))
    assert sent == [('คึนจองจอน (ท้องพระโรง)은', None)]


def test_substituted_names_still_link_cards():
    from app.core import use_vendor
    use_vendor()
    import cards
    metas = [{'type': 'building', 'serial': 160, 'name': '근정전', 'name_en': 'Geunjeongjeon (Throne Hall)',
              'name_th': 'คึนจองจอน (ท้องพระโรง)'}]
    en = 'Geunjeongjeon (Throne Hall) is the main hall of Gyeongbokgung Palace.'
    assert cards.link_names(en, metas, 'English').startswith('[Geunjeongjeon](card:b-160) (Throne Hall)')
    th = 'คึนจองจอน (ท้องพระโรง) เป็นท้องพระโรงหลัก'
    assert '(card:b-160)' in cards.link_names(th, metas, 'ภาษาไทย')


def test_placeholder_roman_and_restore():
    from app.live.translate import placeholder_terms, restore_terms
    text, marks = placeholder_terms('근정전에서 경회루까지, 근정전', 'th', TABLE, style='roman')
    assert text == 'Geunjeongjeon에서 Gyeonghoeru까지, Geunjeongjeon'
    assert marks == {'Geunjeongjeon': TABLE['근정전']['th'], 'Gyeonghoeru': TABLE['경회루']['th']}
    out = restore_terms('เดินจาก Geunjeongjeon ถึง gyeonghoeru', marks)  # 대소문자 무시
    assert out == f"เดินจาก {TABLE['근정전']['th']} ถึง {TABLE['경회루']['th']}"


def test_placeholder_token_and_word_boundary():
    from app.live.translate import placeholder_terms, restore_terms
    table = {**TABLE, '정전': {'en': 'Jeongjeon (main hall of a palace)', 'th': 'ชองจอน'}}
    text, marks = placeholder_terms('근정전은 정전입니다', 'th', table, style='token')
    assert text == 'GGT0은 GGT1입니다'
    # 로마자: Geunjeongjeon 안의 Jeongjeon 은 되돌리지 않음
    _, marks = placeholder_terms('근정전은 정전입니다', 'th', table, style='roman')
    assert restore_terms('Geunjeongjeon is Jeongjeon', marks) == f"{TABLE['근정전']['th']} is ชองจอน"
    assert placeholder_terms('정전', 'ja', table) == ('정전', {})  # 그 언어 표기가 없으면 그대로


def test_bundle_terms_are_left_alone():
    """묶음 표기 (영문 이름에 / 나 and) 는 바꿔 넣지 않음 (안기겸 검토 2026-11-10)"""
    from app.live.translate import is_bundle, placeholder_terms, substitute_terms, wrap_terms
    assert is_bundle('Changgeon / Junggeon / Jaegeon / Bogwon / Sosil (Foundation / Reconstruction)')
    assert is_bundle('Gukbo and Bomul (National Treasure and Treasure)')
    assert not is_bundle('Geunjeongjeon (Throne Hall)')
    assert not is_bundle('Seokjo (Stone Lantern and Base)')  # 괄호 설명 속 and 는 상관없음
    table = {**TABLE, '복원': {'en': 'Changgeon / Junggeon / Bogwon (Foundation / Restoration)', 'th': 'x'}}
    assert substitute_terms('근정전을 복원했습니다', 'en', table) == 'Geunjeongjeon (Throne Hall)을 복원했습니다'
    assert placeholder_terms('복원했습니다', 'th', table) == ('복원했습니다', {})
    assert wrap_terms('복원했습니다', 'en', table) == ('복원했습니다', {})


def test_wrap_and_unwrap_terms():
    from app.live.translate import unwrap_terms, wrap_terms
    text, marks = wrap_terms('근정전은 경회루와 근정전', 'th', TABLE)
    assert text == ('<span translate="no">Geunjeongjeon</span>은 <span translate="no">Gyeonghoeru</span>와 '
                    '<span translate="no">Geunjeongjeon</span>')
    assert marks == {'Geunjeongjeon': TABLE['근정전']['th'], 'Gyeonghoeru': TABLE['경회루']['th']}
    out = unwrap_terms('<span translate="no">Geunjeongjeon</span> &amp; <SPAN translate=\'no\'> Gyeonghoeru </SPAN>', marks)
    assert out == f"{TABLE['근정전']['th']} & {TABLE['경회루']['th']}"
    # Translate 가 표시를 없앴으면 남은 이름으로 되돌림
    assert unwrap_terms('Geunjeongjeon is big', marks) == f"{TABLE['근정전']['th']} is big"
    assert wrap_terms('정전', 'th', TABLE) == ('정전', {})  # 그 언어 표기가 없으면 그대로


def test_notranslate_mode_is_default(monkeypatch):
    monkeypatch.delenv('TRANSLATE_TERM_MODE')
    monkeypatch.delenv('TRANSLATE_TERMS_PATH', raising=False)
    sent = []

    class C:
        def translate_text(self, **kw):
            sent.append((kw['Text'], kw.get('TerminologyNames')))
            return {'TranslatedText': kw['Text'].replace('은', ' is').replace('입니다.', '.')}
    t = AwsTranslator(C())
    assert t.mode == 'notranslate'
    en = run(t.translate('근정전은 경복궁의 정전입니다.', 'en'))
    # 경복궁은 괄호 풀이 없는 일반 단어로 용어집에 있음 (AI 리포 PR #3)
    assert sent[0] == ('<span translate="no">Geunjeongjeon</span>은 <span translate="no">Gyeongbokgung Palace</span>의 '
                       '<span translate="no">Jeongjeon</span>입니다.', None)
    assert en == 'Geunjeongjeon (Throne Hall) is Gyeongbokgung Palace의 Jeongjeon (main hall of a palace).'


@pytest.mark.parametrize('ko, out', [
    ('왕이 연회를 열었다', '<span translate="no">the king</span>이 연회를 열었다'),
    ('왕의 침전', '<span translate="no">the king</span>의 침전'),
    ('왕.', '<span translate="no">the king</span>.'),
    ('"왕"은', '"<span translate="no">the king</span>"은'),
    ('왕실과 왕권, 왕명, 왕위, 왕대비', '왕실과 왕권, 왕명, 왕위, 왕대비'),  # 1글자 용어는 조사 앞에서만
    ('근정전실', '<span translate="no">Geunjeongjeon</span>실'),  # 2글자 이상은 그대로 (뒤에 무엇이 붙어도 됨)
])
def test_one_letter_term_only_before_particle(ko, out):
    """cornch-k 리뷰 (2026-11-10): '왕 → the king' 을 넣어도 '왕실' 이 'the king실' 이 되지 않게"""
    from app.live.translate import wrap_terms
    table = {**TABLE, '왕': {'en': 'the king', 'th': ''}}
    assert wrap_terms(ko, 'en', table)[0] == out


def test_one_letter_terms_are_loaded(tmp_path):
    from app.live.translate import _load_glossary
    path = tmp_path / 't.csv'
    path.write_text('ko,en,th\n왕,the king,\n근정전,Geunjeongjeon (Throne Hall),\n경복궁 중건,x,\n', encoding='utf-8')
    assert set(_load_glossary(str(path))) == {'왕', '근정전'}  # 띄어 쓴 용어는 아직 뺌


@pytest.mark.parametrize('ko, out', [
    ('왕이 연회를 열었다', 'The king이 연회를 열었다'),
    ('왕의 명령', 'The king의 명령'),
    ('왕실과 왕권', '왕실과 왕권'),
])
def test_real_glossary_has_king(ko, out):
    """AI 리포 용어집(gunggeum-ai-stt PR #3, 332개)의 '왕 → the king' 이 실제 파일에서 동작하는지"""
    from app.live.translate import DEFAULT_TERMS, _load_glossary, unwrap_terms, wrap_terms
    table = _load_glossary(str(DEFAULT_TERMS))
    assert table['왕']['en'] == 'the king'
    wrapped, marks = wrap_terms(ko, 'en', table)
    assert unwrap_terms(wrapped, marks) == out


def test_unwrap_capitalizes_sentence_start():
    """'왕비는 …' → 'the queen lived …' 가 아니라 'The queen lived …'"""
    from app.live.translate import unwrap_terms
    marks = {'the queen': 'the queen'}
    assert unwrap_terms('<span translate="no">the queen</span> lived here.', marks) == 'The queen lived here.'
    assert unwrap_terms('"<span translate="no">the queen</span>" lived', marks) == '"The queen" lived'
    assert unwrap_terms('Later <span translate="no">the queen</span> lived', marks) == 'Later the queen lived'
    assert unwrap_terms('the king and the <span translate="no">the queen</span>', marks) == 'the king and the queen'


# ---------- 이슈 #16 공지 자동 번역 품질 ----------

NOTICE_TABLE = {**TABLE, '대비': {'en': 'Daebi (Queen Dowager)', 'th': 'แทบี'},
                '조정': {'en': 'Jojeong (Royal Court / Main Courtyard)', 'th': 'โจจอง'},
                '광화문': {'en': 'Gwanghwamun (Palace Gate)', 'th': 'ควังฮวามุน'},
                '승하': {'en': 'Seungha (Passing of a Monarch)', 'th': 'ซึงฮา'}}
W = '<span translate="no">{}</span>'.format


@pytest.mark.parametrize('ko, out', [
    ('취소합니다.\n근정전·경회루 일대는', f'취소합니다.\n{W("Geunjeongjeon")}·{W("Gyeonghoeru")} 일대는'),  # 줄바꿈·가운뎃점 뒤
    ('(근정전) 앞', f'({W("Geunjeongjeon")}) 앞'),
    ('  근정전은\n\n끝.  ', f'  {W("Geunjeongjeon")}은\n\n끝.  '),  # 공백·줄바꿈 그대로
    ('용어 없음.\n둘째 줄', '용어 없음.\n둘째 줄'),
    ('', ''),
])
def test_terms_found_after_newline_and_symbols(ko, out):
    from app.live.translate import wrap_terms
    assert wrap_terms(ko, 'en', NOTICE_TABLE)[0] == out


def test_substitute_keeps_layout():
    from app.live.translate import substitute_terms
    assert substitute_terms('안내\n근정전·경회루', 'en', TABLE) == '안내\nGeunjeongjeon (Throne Hall)·Gyeonghoeru (Banquet Pavilion)'


@pytest.mark.parametrize('ko, notice, out', [
    ('태풍 북상에 대비해 통제합니다.', True, '태풍 북상에 대비해 통제합니다.'),       # 동사
    ('오후 2시로 조정됩니다.', True, '오후 2시로 조정됩니다.'),
    ('폭염 대비 안내', True, '폭염 대비 안내'),                                    # 일반 낱말
    ('조정에서 조회를 열었다', True, f'{W("Jojeong")}에서 조회를 열었다'),          # 장소로 쓰인 조정은 감쌈
    ('오후 2시로 조정됩니다.', False, f'오후 2시로 {W("Jojeong")}됩니다.'),         # 자막은 그대로
    ('왕이 승하했습니다', False, f'왕이 {W("Seungha")}했습니다'),                  # 자막: 동사로 쓰여도 감쌈 (승하 → won 방지)
])
def test_notice_skips_verbs_and_plain_words(ko, notice, out):
    from app.live.translate import wrap_terms
    assert wrap_terms(ko, 'en', NOTICE_TABLE, notice=notice)[0] == out


@pytest.mark.parametrize('ko, out', [
    ('광화문 야간 조명 점등 시간을 연장합니다.', '광화문의 야간 조명 점등 시간을 연장합니다.'),
    ('안내\n근정전 지붕 보수 공사로', '안내\n근정전의 지붕 보수 공사로'),
    ('광화문 앞 해설', '광화문의 앞 해설'),
    ('오늘 광화문 앞 해설', '오늘 광화문 앞 해설'),   # 줄 첫머리만
    ('광화문은 닫습니다', '광화문은 닫습니다'),       # 이미 조사가 있음
    ('광화문', '광화문'),
])
def test_add_ui(ko, out):
    from app.live.translate import add_ui
    assert add_ui(ko, ['근정전', '광화문']) == out


@pytest.mark.parametrize('ko, out', [
    ('2026. 8. 12.(수) 오후 2시부로', '2026년 8월 12일(수) 오후 2시부로'),
    ('2026.12.1 휴관', '2026년 12월 1일 휴관'),
    ('2026. 12. 8.(화) ~ 12. 19.(토)', '2026년 12월 8일(화) ~ 12월 19일(토)'),  # 기간 끝 (N25)
    ('2026.12.8~12.19 휴관', '2026년 12월 8일~12월 19일 휴관'),
    ('09:00 ~ 17:00', '09:00 ~ 17:00'),
    ('2026. 13. 1.', '2026. 13. 1.'),            # 날짜가 아님
    ('전화 02-3700-3900', '전화 02-3700-3900'),
])
def test_korean_dates(ko, out):
    from app.live.translate import korean_dates
    assert korean_dates(ko) == out


def test_angle_headers_round_trip():
    from app.live.translate import hide_angles, show_angles
    assert hide_angles('<긴급> 해설 취소') == ('[긴급] 해설 취소', True)
    assert show_angles('[ Emergency ] Tour canceled') == '<Emergency> Tour canceled'
    assert hide_angles('[안내] <긴급>') == ('[안내] <긴급>', False)  # 대괄호가 이미 있으면 그대로
    assert hide_angles('괄호 없음') == ('괄호 없음', False)


def test_wrap_years():
    from app.live.translate import wrap_years
    assert wrap_years('1985년에 보물로') == '<span translate="no">1985</span>년에 보물로'
    assert wrap_years('12345년, 2시') == '12345년, 2시'


@pytest.mark.parametrize('tr, lang, out', [
    ('in <span translate="no">1985</span>.', 'en', 'in 1985.'),
    ("in '<span translate=\"no\">2018</span>'.", 'en', 'in 2018.'),                  # 따옴표 뗌
    ('ถูกกำหนดในปี <span translate="no">1985</span>', 'th', 'ถูกกำหนดในปี 1985'),        # 이미 ปี
    ('ถูกกำหนดเป็นสมบัติใน<span translate="no">1985</span>', 'th', 'ถูกกำหนดเป็นสมบัติในปี 1985'),  # ปี 붙임
    ('<span translate="no">1927</span> ถูกย้าย', 'th', 'ปี 1927 ถูกย้าย'),
    ('1 ธันวาคม <span translate="no">2026</span>', 'th', '1 ธันวาคม 2026'),           # 달 이름 뒤
    ('ค.ศ. <span translate="no">1395</span>', 'th', 'ค.ศ. 1395'),
])
def test_put_years(tr, lang, out):
    from app.live.translate import put_years
    assert put_years(tr, lang) == out


def test_extra_years():
    from app.live.translate import extra_years
    assert extra_years('2015년에 복원', 'restored in 1967 and 2015', {})
    assert not extra_years('2015년에 복원', 'restored in 2015', {})
    assert not extra_years('임진왜란 때', 'during Imjin War (1592–1598)', {'Imjin': 'Imjin War (1592–1598)'})  # 용어 표기 연도는 허용
    assert not extra_years('전화 02-3700-3900', 'Tel 02-3700-3900', {})


class Recorder:
    """보낸 글을 적고, replies 를 차례로 돌려줌 (없으면 보낸 글 그대로)"""

    def __init__(self, *replies):
        self.sent, self.replies = [], list(replies)

    def translate_text(self, **kw):
        self.sent.append(kw['Text'])
        return {'TranslatedText': self.replies.pop(0) if self.replies else kw['Text']}


@pytest.fixture
def notranslate(monkeypatch):
    monkeypatch.setenv('TRANSLATE_TERM_MODE', 'notranslate')
    monkeypatch.delenv('TRANSLATE_TERMS_PATH', raising=False)


def test_years_protected_in_subtitles(notranslate):
    c = Recorder('ถูกกำหนดเป็นสมบัติใน<span translate="no">1985</span>')
    out = run(AwsTranslator(c).translate('1985년에 보물로 지정됐습니다.', 'th'))
    assert c.sent == ['<span translate="no">1985</span>년에 보물로 지정됐습니다.']
    assert out == 'ถูกกำหนดเป็นสมบัติในปี 1985'


def test_invented_year_retranslates_without_year_protection(notranslate):
    c = Recorder('restored in 1967 <span translate="no">2015</span>', 'restored in 2015')
    out = run(AwsTranslator(c).translate('2015년에 복원했습니다.', 'en'))
    assert out == 'restored in 2015'
    assert c.sent == ['<span translate="no">2015</span>년에 복원했습니다.', '2015년에 복원했습니다.']


def test_notice_mode_end_to_end(notranslate):
    c = Recorder()
    text = '<긴급> 2026. 8. 12.(수) 해설 취소\n광화문 야간 조명을 조정합니다.\n근정전·경회루 일대는 폭염 대비 통제'
    out = run(AwsTranslator(c).translate(text, 'en', notice=True))
    assert c.sent == ['[긴급] <span translate="no">2026</span>년 8월 12일(수) 해설 취소\n'
                      '<span translate="no">Gwanghwamun</span>의 야간 조명을 조정합니다.\n'
                      '<span translate="no">Geunjeongjeon</span>·<span translate="no">Gyeonghoeru</span> 일대는 폭염 대비 통제']
    assert out.startswith('<긴급> 2026년 8월 12일(수)')
    assert 'Gwanghwamun (Palace Gate)의' in out and 'Geunjeongjeon (Throne Hall)·Gyeonghoeru (Banquet Pavilion)' in out


def test_subtitles_skip_notice_steps(notranslate):
    c = Recorder()
    run(AwsTranslator(c).translate('광화문 앞에서 조정됩니다', 'en'))
    assert c.sent == ['<span translate="no">Gwanghwamun</span> 앞에서 <span translate="no">Jojeong</span>됩니다']


def test_echo_accepts_notice():
    from app.live.translate import EchoTranslator
    assert run(EchoTranslator().translate('안내', 'en', notice=True)) == '안내'


PAREN_TABLE = {**TABLE, '사정전': {'en': 'Sajeongjeon (Royal Council Hall)', 'th': 'ซาจองจอน (ท้องพระโรงทรงงาน)'},
               '편전': {'en': 'Pyeonjeon (Royal Council Hall)', 'th': 'พยอนจอน (ท้องพระโรงว่าราชการ)'},
               '월대': {'en': 'Woldae (Raised Platform)', 'th': 'วอลแด'}}


@pytest.mark.parametrize('ko, lang, out', [
    ('사정전(편전)은 왕의 집무실', 'en', 'Sajeongjeon (Royal Council Hall) (Pyeonjeon)은 왕의 집무실'),
    ('사정전(편전)은', 'th', 'ซาจองจอน (ท้องพระโรงทรงงาน) (พยอนจอน)은'),
    ('사정전(편전). 편전은', 'en', 'Sajeongjeon (Royal Council Hall) (Pyeonjeon). Pyeonjeon (Royal Council Hall)은'),  # 밖의 편전은 카드 표기
    ('근정전 월대(근정전 앞 계단 구역)', 'en',
     'Geunjeongjeon (Throne Hall) Woldae (Raised Platform)(Geunjeongjeon (Throne Hall) 앞 계단 구역)'),  # 괄호 안에 다른 말 → 그대로
    ('사정전(편전이)', 'en', 'Sajeongjeon (Royal Council Hall)(Pyeonjeon (Royal Council Hall)이)'),  # 괄호 안이 용어 하나가 아님
])
def test_term_in_paren_after_term_uses_name_only(ko, lang, out):
    """안기겸 리뷰 (2026-11-22): 용어 바로 뒤 괄호 안에 용어 하나만 있으면 괄호 안은 이름만"""
    from app.live.translate import unwrap_terms, wrap_terms
    wrapped, marks = wrap_terms(ko, lang, PAREN_TABLE)
    assert unwrap_terms(wrapped, marks) == out
