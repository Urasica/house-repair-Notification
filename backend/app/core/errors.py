from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.domain.constants import ErrorCode


class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str, status: int, details=None):
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def error_response(request: Request, error: AppError) -> JSONResponse:
    trace_id = str(getattr(request.state, "trace_id", uuid4()))
    response = JSONResponse(
        status_code=error.status,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
                "traceId": trace_id,
            }
        },
        headers={"Cache-Control": "no-store", "X-Trace-Id": trace_id},
    )
    if error.code == ErrorCode.RATE_LIMITED:
        response.headers["Retry-After"] = str(error.details.get("retryAfterSeconds", 60))
    if error.code == ErrorCode.AUTH_EXPIRED:
        settings = request.app.state.settings
        response.delete_cookie(
            settings.auth_cookie_name,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite="lax",
            path="/",
        )
    return response


async def app_error_handler(request: Request, error: AppError):
    return error_response(request, error)


async def validation_error_handler(request: Request, error: RequestValidationError):
    fields = [
        {"field": ".".join(map(str, item["loc"])), "type": item["type"]} for item in error.errors()
    ]
    return error_response(
        request,
        AppError(ErrorCode.VALIDATION_ERROR, "입력 값을 확인해 주세요.", 422, {"fields": fields}),
    )


async def http_error_handler(request: Request, error: HTTPException):
    code = ErrorCode.NOT_FOUND if error.status_code == 404 else ErrorCode.VALIDATION_ERROR
    return error_response(request, AppError(code, "요청을 확인해 주세요.", error.status_code))


async def unexpected_error_handler(request: Request, error: Exception):
    return error_response(
        request, AppError(ErrorCode.SERVICE_UNAVAILABLE, "잠시 후 다시 시도해 주세요.", 503)
    )
