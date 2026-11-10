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
    assert split_particles('"근정전"은', terms) == '"근정전 "은'  # 앞 따옴표 뒤도 용어 시작으로 봄


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
    assert sent == [('Geunjeongjeon (Throne Hall)은 경복궁의 Jeongjeon (main hall of a palace)입니다.', None),
                    ('GGT0은 경복궁의 GGT1입니다.', None)]
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
    # 경복궁은 아직 용어집에 없음 (검토 1번: 왕·왕비·경복궁 추가는 AI 리포 용어집에서)
    assert sent[0] == ('<span translate="no">Geunjeongjeon</span>은 경복궁의 <span translate="no">Jeongjeon</span>입니다.', None)
    assert en == 'Geunjeongjeon (Throne Hall) is 경복궁의 Jeongjeon (main hall of a palace).'


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
