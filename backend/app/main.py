from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.exceptions import HTTPException

from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.domain.constants import ErrorCode
from app.schemas.catalog import Catalog
from app.schemas.contracts import ErrorResponse, Readiness


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
            pool_timeout=3,
        )
        yield
        await app.state.engine.dispose()

    app = FastAPI(title="우리집 보수 길잡이 API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)

    @app.middleware("http")
    async def request_metadata(request: Request, call_next):
        request.state.trace_id = uuid4()
        response = await call_next(request)
        response.headers["X-Trace-Id"] = str(request.state.trace_id)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", response_model=Readiness, responses={503: {"model": ErrorResponse}})
    async def ready(request: Request) -> Readiness:
        try:
            async with request.app.state.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as error:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE, "서비스 준비 상태를 확인할 수 없어요.", 503
            ) from error
        return Readiness(status="ok", catalog_ready=False, rag_ready=False)

    @app.get("/api/v1/catalog", response_model=Catalog, responses={503: {"model": ErrorResponse}})
    async def catalog() -> Catalog:
        raise AppError(ErrorCode.CATALOG_NOT_READY, "증상 목록을 준비하고 있어요.", 503)

    return app


app = create_app()
