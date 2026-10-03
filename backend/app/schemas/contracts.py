from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from app.domain.constants import (
    AccessMode,
    ErrorCode,
    GuidanceStatus,
    HousingType,
    RequestKind,
    RequestStatus,
)
from app.schemas.base import APIModel
from app.schemas.catalog import Question


class Context(APIModel):
    housing_type: HousingType | None = None
    room_id: str | None = None
    facility_id: str | None = None
    symptom_id: str | None = None
    description: str = Field(default="", max_length=1000)
    answers: dict[str, str] = Field(default_factory=dict)


class ContextUpdate(APIModel):
    expected_revision: int = Field(ge=0)
    context: Context


class QuestionsResponse(APIModel):
    catalog_version: str
    revision: int = Field(ge=0)
    questions: list[Question]


class EvaluationRequest(APIModel):
    request_id: UUID
    expected_revision: int = Field(ge=0)


class ChatRequest(EvaluationRequest):
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value


class Session(APIModel):
    id: UUID
    access_mode: AccessMode
    catalog_version: str
    knowledge_release_id: UUID | None
    revision: int = Field(ge=0)
    context: Context
    current_result_id: UUID | None
    created_at: AwareDatetime
    expires_at: AwareDatetime


class User(APIModel):
    id: UUID
    email: str
    created_at: AwareDatetime


class AuthState(APIModel):
    user: User | None
    csrf_token: str | None


class Citation(APIModel):
    chunk_id: UUID
    document_version_id: UUID
    kind: Literal["LAW_CRITERIA", "LH_OPERATION", "SAFETY_SOURCE"]
    use: Literal["RELATED", "APPLICABLE"]
    title: str
    locator: str
    url: str
    effective_date: str | None
    reviewed_at: AwareDatetime
    review_until: AwareDatetime


class ResultSummary(APIModel):
    housing_label: str
    room_label: str
    facility_label: str
    symptom_label: str
    description: str
    answer_labels: list[str]


class GuidanceResult(APIModel):
    id: UUID
    session_id: UUID | None
    saved_to_history: bool
    catalog_version: str
    knowledge_release_id: UUID | None
    context_revision: int = Field(ge=0)
    status: GuidanceStatus
    reason_codes: list[
        Literal[
            "HAZARD_SIGNAL",
            "HOUSING_OUT_OF_SCOPE",
            "MISSING_INPUT",
            "NO_APPLICABLE_SOURCE",
            "SOURCE_CONFLICT",
            "SOURCE_UNAVAILABLE",
            "MATCHED_OPERATION_RULE",
        ]
    ]
    summary: ResultSummary
    guidance: list[str]
    checks: list[str]
    follow_up_questions: list[str]
    contact_draft: str
    citations: list[Citation]
    disclaimer: str
    engine_version: str
    generated_at: AwareDatetime
    retained_until: AwareDatetime
    is_current: bool


class ChatMessage(APIModel):
    id: UUID
    request_id: UUID
    role: Literal["USER", "ASSISTANT"]
    content: str
    citations: list[Citation]
    created_at: AwareDatetime
    is_current: bool


class ChatResponse(APIModel):
    request_id: UUID
    context_revision: int = Field(ge=0)
    answer_mode: Literal["GROUNDED", "CLARIFY", "TEMPLATE"]
    status: GuidanceStatus
    user_message: ChatMessage
    assistant_message: ChatMessage
    follow_up_questions: list[str]
    disclaimer: str
    is_current: bool


class RequestState(APIModel):
    request_id: UUID
    kind: RequestKind
    state: RequestStatus
    retry_after_ms: int | None
    response: GuidanceResult | ChatResponse | None


class ErrorDetail(APIModel):
    code: ErrorCode
    message: str
    details: dict = Field(default_factory=dict)
    trace_id: UUID


class ErrorResponse(APIModel):
    error: ErrorDetail


class Readiness(APIModel):
    status: Literal["ok"]
    catalog_ready: bool
    rag_ready: bool


CONTRACT_MODELS = (
    Context,
    ContextUpdate,
    QuestionsResponse,
    EvaluationRequest,
    ChatRequest,
    Session,
    User,
    AuthState,
    Citation,
    GuidanceResult,
    ChatMessage,
    ChatResponse,
    RequestState,
    ErrorResponse,
    Readiness,
)
