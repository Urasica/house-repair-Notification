"""Member chat policy, minimal external projection, and historical validity."""

import asyncio
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.db.models import Consultation
from app.domain.constants import (
    DISCLAIMER,
    INSUFFICIENT_INFORMATION_MESSAGE,
    KNOWLEDGE_UNAVAILABLE_MESSAGE,
    NO_APPLICABLE_GUIDANCE_MESSAGE,
    OPENAI_DISABLED_MESSAGE,
    OPENAI_UNAVAILABLE_MESSAGE,
    GuidanceStatus,
)
from app.schemas.contracts import ChatMessage, ChatResponse
from app.services.chat_context import chat_policy
from app.services.embeddings import Embeddings, EmbeddingUnavailable
from app.services.generation import PROMPT_VERSION, GenerationUnavailable, Responses, annex_texts
from app.services.repair_examples import repair_examples
from app.services.retrieval import question_purpose, retrieve, revalidate_citations
from app.services.survey_policy import survey_policy


def project_question(content):
    """Allowlist only purpose and explicit legal locators; no regex-only PII promise."""
    locators = re.findall(r"제\s*\d{1,3}\s*조(?:의\s*\d{1,2})?|별표\s*\d{1,2}", content)
    return question_purpose(content) + " " + " ".join(dict.fromkeys(locators))


def fallback(response, message=KNOWLEDGE_UNAVAILABLE_MESSAGE):
    return response.model_copy(
        update={
            "answer_mode": "TEMPLATE",
            "status": GuidanceStatus.GUIDANCE_UNAVAILABLE,
            "follow_up_questions": [],
            "reference_examples": [],
            "assistant_message": response.assistant_message.model_copy(
                update={"content": message, "citations": []}
            ),
        }
    )


def citation_check(response, snapshot):
    return SimpleNamespace(
        citations=response.assistant_message.citations,
        knowledge_release_id=snapshot.knowledge_release_id,
        catalog_version=snapshot.catalog_version,
    )


async def chat_response(
    snapshot,
    catalog,
    settings,
    content,
    request_id,
    recent,
    *,
    database,
    embeddings=None,
    generator=None,
    deadline=None,
):
    status, questions, guidance = chat_policy(snapshot.context, content)
    purpose = question_purpose(content)
    now = datetime.now(UTC)
    response = ChatResponse(
        request_id=request_id,
        context_revision=snapshot.revision,
        answer_mode="CLARIFY" if status == "NEED_MORE_INFO" else "TEMPLATE",
        status=status,
        user_message=ChatMessage(
            id=uuid4(),
            request_id=request_id,
            role="USER",
            content=content,
            citations=[],
            created_at=now,
            is_current=True,
        ),
        assistant_message=ChatMessage(
            id=uuid4(),
            request_id=request_id,
            role="ASSISTANT",
            content=guidance or INSUFFICIENT_INFORMATION_MESSAGE,
            citations=[],
            created_at=now,
            is_current=True,
        ),
        follow_up_questions=questions,
        reference_examples=(
            repair_examples(catalog, snapshot.context, status) if purpose == "OPERATION" else []
        ),
        disclaimer=DISCLAIMER,
        is_current=True,
    )
    # A conservative interruption, never a diagnosis or an inferred repair rule.
    survey = (
        survey_policy(catalog, snapshot.context)
        if snapshot.context.room_id and snapshot.context.facility_id and snapshot.context.symptom_id
        else None
    )
    if (survey and survey.status == GuidanceStatus.SAFETY_PRIORITY) or re.search(
        r"가스\s*(?:냄새|누출)|타는\s*냄새|연기|스파크|불꽃|불이\s*났|감전|붕괴|떨어지고", content
    ):
        return response.model_copy(
            update={
                "status": GuidanceStatus.SAFETY_PRIORITY,
                "answer_mode": "TEMPLATE",
                "follow_up_questions": [],
                "reference_examples": [],
                "assistant_message": response.assistant_message.model_copy(
                    update={
                        "content": "일반 보수 안내보다 안전 확인이 우선이에요. "
                        "관리사무소 또는 담당 기관에 직접 문의해 주세요."
                    }
                ),
            }
        )
    if status != "NEED_CONFIRMATION" or guidance:
        return response
    if not settings.openai_enabled:
        return fallback(response, OPENAI_DISABLED_MESSAGE)
    if not snapshot.knowledge_release_id:
        return fallback(response)
    # Free text and raw conversation never leave the server. Selected labels are reviewed.
    labels = []
    for field, items in [
        ("housing_type", catalog.housing_types),
        ("room_id", catalog.rooms),
        ("facility_id", catalog.facilities),
        ("symptom_id", catalog.symptoms),
    ]:
        labels.extend(item.label for item in items if item.id == getattr(snapshot.context, field))
    for question in survey.questions if survey else []:
        labels.extend(
            f"{question.label}: {option.label}"
            for option in question.options
            if option.value == survey.context.answers.get(question.question_id)
        )
    query = " · ".join([project_question(content), *labels])
    loop = asyncio.get_running_loop()
    deadline = deadline or loop.time() + settings.chat_timeout_seconds - 2
    try:
        async with asyncio.timeout_at(deadline):
            vector = (
                await (embeddings or Embeddings(settings)).embed(
                    [query], timeout=min(5, max(0.01, deadline - loop.time()))
                )
            ).vectors[0]
            async with database.session() as session:
                found = await retrieve(
                    session,
                    snapshot.knowledge_release_id,
                    vector,
                    settings,
                    snapshot.context,
                    purpose=purpose,
                    question=content,
                    catalog_version=snapshot.catalog_version,
                )
            if found.reason == "SOURCE_UNAVAILABLE":
                return fallback(response)
            citations = found.citations(
                excerpts=True,
                explain=purpose == "OPERATION" or found.status == "GUIDANCE_AVAILABLE",
            )
            if found.status != "GUIDANCE_AVAILABLE":
                message = NO_APPLICABLE_GUIDANCE_MESSAGE
                if purpose == "LAW_EXPLANATION":
                    message = "요청하신 조문을 설명할 수 있는 검토 자료를 찾지 못했어요."
                elif snapshot.context.facility_id in {None, "unknown"}:
                    message = (
                        "말씀해 주신 증상만으로는 원인이 된 시설을 특정하기 어려워요. "
                        "관리사무소에 문제가 보이는 위치와 언제부터 그랬는지 알려 주세요."
                    )
                return response.model_copy(
                    update={
                        "assistant_message": response.assistant_message.model_copy(
                            update={
                                "content": (
                                    message
                                    if any(c.explanation for c in citations)
                                    else "\n".join(found.guidance + [message])
                                ),
                                "citations": citations,
                            }
                        ),
                    }
                )
            if purpose == "LAW_EXPLANATION" and all(
                c.explanation for c in found.citations(explain=True) if c.use == "APPLICABLE"
            ):
                return response.model_copy(
                    update={
                        "answer_mode": "GROUNDED",
                        "status": GuidanceStatus.GUIDANCE_AVAILABLE,
                        "assistant_message": response.assistant_message.model_copy(
                            update={
                                "content": (
                                    "구체적인 하자 여부는 현장 상태와 원문에 적힌 조건을 "
                                    "함께 살펴봐야 해요."
                                ),
                                "citations": citations,
                            }
                        ),
                    }
                )
            statements = await (generator or Responses(settings)).generate(
                query, recent, found, purpose, timeout=min(20, max(0.01, deadline - loop.time()))
            )
            prefix = (
                "질문과 관련된 법령 원문이에요. 조문의 조건과 단서를 함께 확인해 주세요. "
                "연결된 별표와 총칙·부칙도 함께 적용되며, "
                "LH 보수·비용·교체 판단을 뜻하지 않아요.\n\n"
                if purpose == "LAW_EXPLANATION"
                else "검토된 운영 안내예요.\n\n"
            )
            return response.model_copy(
                update={
                    "answer_mode": "GROUNDED",
                    "status": GuidanceStatus.GUIDANCE_AVAILABLE,
                    "reference_examples": [],
                    "assistant_message": response.assistant_message.model_copy(
                        update={
                            "content": prefix + "\n\n".join(statements + annex_texts(found)),
                            "citations": citations,
                        }
                    ),
                }
            )
    except (EmbeddingUnavailable, GenerationUnavailable, TimeoutError):
        return fallback(response, OPENAI_UNAVAILABLE_MESSAGE)


def stored_response(response, snapshot, settings):
    return {
        **response.model_dump(mode="json", by_alias=True),
        "_meta": {
            "engine": PROMPT_VERSION,
            "model": settings.openai_chat_model,
            "catalog": snapshot.catalog_version,
            "release": str(snapshot.knowledge_release_id)
            if snapshot.knowledge_release_id
            else None,
        },
    }


async def replay_chat(session, run, settings):
    payload = run.response_json
    response = ChatResponse.model_validate({k: v for k, v in payload.items() if k != "_meta"})
    meta = payload.get("_meta", {})
    row = await session.get(Consultation, run.consultation_id)
    current = bool(
        row
        and row.purpose == "CHAT"
        and row.expires_at > datetime.now(UTC)
        and row.revision == response.context_revision
        and meta.get("engine") == PROMPT_VERSION
        and meta.get("catalog") == row.catalog_version
        and meta.get("release") == (str(row.knowledge_set_id) if row.knowledge_set_id else None)
        and (response.answer_mode != "GROUNDED" or meta.get("model") == settings.openai_chat_model)
    )
    if current and response.assistant_message.citations:
        snapshot = SimpleNamespace(
            knowledge_release_id=row.knowledge_set_id, catalog_version=row.catalog_version
        )
        current = await revalidate_citations(
            session, citation_check(response, snapshot), settings, lock=False
        )
    return response.model_copy(
        update={
            "is_current": current,
            "user_message": response.user_message.model_copy(update={"is_current": current}),
            "assistant_message": response.assistant_message.model_copy(
                update={"is_current": current}
            ),
        }
    )
