"""에러는 모두 {"error": "..."} 한 모양 (deploy/API.md · API 명세서 1.3)"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger('gunggeum.api')


class ApiError(Exception):
    """핸들러에서 raise ApiError(404, '없는 세션') 처럼 씀"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def error(code: int, message: str) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=code)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return error(exc.status, exc.message)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        if any(e.get('type') == 'json_invalid' for e in errors):
            return error(400, '본문이 JSON 이 아닙니다')
        field = next((e['loc'][-1] for e in errors if e.get('loc') and isinstance(e['loc'][-1], str)), 'body')
        return error(400, f'{field} 값을 확인하세요')

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return error(exc.status_code, '없는 경로' if exc.status_code == 404 else str(exc.detail))

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        log.exception('처리 실패: %s %s', request.method, request.url.path)  # 원인은 로그에만
        return error(500, '답변을 만들지 못했습니다')
