import asyncio
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from starlette.exceptions import HTTPException

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.history import router as history_router
from app.api.v1.sessions import router as sessions_router
from app.auth.access import guard_member_path
from app.auth.rate_limit import AuthRateLimiter
from app.auth.security import Passwords
from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.db.session import Database
from app.schemas.catalog import Catalog, Question
from app.schemas.contracts import CONTRACT_MODELS, ErrorResponse, Readiness
from app.services.catalog import get_catalog
from app.services.chat import chat_response
from app.services.guidance import evaluate_survey
from app.services.locks import ConsultationLocks
from app.services.readiness import get_readiness

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.database = database or Database(settings)
        try:
            await app.state.database.initialize()
        except AppError:
            logger.warning("Database is not ready; live endpoint remains available")
        try:
            yield
        finally:
            await app.state.database.dispose()

    app = FastAPI(
        title="우리집 보수 길잡이 API",
        version="0.1.0",
        lifespan=lifespan,
        responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    app.state.settings = settings
    app.state.passwords = Passwords()
    app.state.auth_rate_limiter = AuthRateLimiter()
    app.state.consultation_locks = ConsultationLocks()
    app.state.question_deletion_locks = ConsultationLocks()
    app.state.chat_budget_lock = asyncio.Lock()

    async def survey_evaluator(snapshot, catalog, runtime_settings):
        return await evaluate_survey(
            snapshot, catalog, runtime_settings, database=app.state.database
        )

    app.state.evaluate_survey = survey_evaluator

    async def chat_evaluator(*args, **kwargs):
        return await chat_response(*args, **kwargs, database=app.state.database)

    app.state.chat_response = chat_evaluator
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)

    @app.middleware("http")
    async def request_metadata(request: Request, call_next):
        request.state.trace_id = uuid4()
        try:
            await guard_member_path(request)
            response = await call_next(request)
        except AppError as error:
            response = await app_error_handler(request, error)
        except Exception as error:
            logger.error(
                "Unhandled request failure: %s trace=%s",
                type(error).__name__,
                request.state.trace_id,
            )
            response = await unexpected_error_handler(request, error)
        response.headers["X-Trace-Id"] = str(request.state.trace_id)
        if request.url.path.startswith(("/api/", "/health/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health/live", operation_id="getLive")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", response_model=Readiness, operation_id="getReadiness")
    async def ready(request: Request) -> Readiness:
        db = request.app.state.database
        await db.initialize()
        async with db.session() as session:
            return await get_readiness(session, settings)

    @app.get(
        "/api/v1/catalog",
        response_model=Catalog,
        operation_id="getCatalog",
        responses={404: {"model": ErrorResponse}},
    )
    async def catalog(
        request: Request, version: str | None = Query(default=None, min_length=1, max_length=80)
    ) -> Catalog:
        db = request.app.state.database
        await db.initialize()
        async with db.session() as session:
            return await get_catalog(session, version)

    def openapi_contract() -> dict:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            components = schema.setdefault("components", {}).setdefault("schemas", {})
            for model in (*CONTRACT_MODELS, Question):
                definition = model.model_json_schema(
                    by_alias=True, mode="serialization", ref_template="#/components/schemas/{model}"
                )
                for name, value in definition.pop("$defs", {}).items():
                    components.setdefault(name, value)
                components.setdefault(model.__name__, definition)
            app.openapi_schema = schema
        return app.openapi_schema

    app.include_router(auth_router)
    app.include_router(sessions_router)
    app.include_router(history_router)
    app.include_router(chat_router)
    app.openapi = openapi_contract
    return app


app = create_app()
