"""자막 번역. TRANSLATE_PROVIDER=aws (Amazon Translate, 기본) | echo (개발용: 한국어 그대로)"""
import asyncio
import logging

from app.settings import env

log = logging.getLogger('gunggeum.translate')


class EchoTranslator:
    """키 없이 흐름만 확인할 때. 번역하지 않고 한국어를 그대로 돌려줌"""

    async def translate(self, text: str, lang: str) -> str:
        return text


def is_missing_terminology(e: Exception) -> bool:
    """용어집 이름이 AWS 에 없음 (botocore ClientError 의 오류 코드로 판단)"""
    return getattr(e, 'response', {}).get('Error', {}).get('Code') == 'ResourceNotFoundException'


class AwsTranslator:
    """Amazon Translate. 전각명·궁궐 용어 표기 고정은 Custom Terminology (TRANSLATE_TERMINOLOGY=이름).
    Translate 는 요청 하나에 용어집을 하나만 받으므로 여러 개를 적으면 첫 번째만 씀.
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

    async def _call(self, text: str, lang: str, terminology: str | None) -> str:
        extra = {'TerminologyNames': [terminology]} if terminology else {}
        res = await asyncio.to_thread(self.client.translate_text, Text=text, SourceLanguageCode='ko',
                                      TargetLanguageCode=lang, **extra)
        return res['TranslatedText']

    async def translate(self, text: str, lang: str) -> str:
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
