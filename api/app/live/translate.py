"""자막 번역. TRANSLATE_PROVIDER=aws (Amazon Translate, 기본) | echo (개발용: 한국어 그대로)"""
import asyncio

from app.settings import env


class EchoTranslator:
    """키 없이 흐름만 확인할 때. 번역하지 않고 한국어를 그대로 돌려줌"""

    async def translate(self, text: str, lang: str) -> str:
        return text


class AwsTranslator:
    """Amazon Translate. 전각명 표기 고정은 Custom Terminology (TRANSLATE_TERMINOLOGY=이름[,이름])"""

    def __init__(self):
        import boto3
        self.client = boto3.client('translate', region_name=env('AWS_REGION', 'ap-northeast-2'))
        self.terms = [t.strip() for t in env('TRANSLATE_TERMINOLOGY').split(',') if t.strip()]

    async def translate(self, text: str, lang: str) -> str:
        extra = {'TerminologyNames': self.terms} if self.terms else {}
        res = await asyncio.to_thread(self.client.translate_text, Text=text, SourceLanguageCode='ko',
                                      TargetLanguageCode=lang, **extra)
        return res['TranslatedText']


def make_translator():
    return EchoTranslator() if env('TRANSLATE_PROVIDER', 'aws') == 'echo' else AwsTranslator()
