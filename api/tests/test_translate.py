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
