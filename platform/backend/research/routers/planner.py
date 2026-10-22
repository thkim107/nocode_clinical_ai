from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from collections import OrderedDict
import asyncio
from datetime import datetime
from pytz import timezone
import traceback
import re

from research import llm_manager
from research.llm_manager import to_json
from research.prompts import PROMPT_LANG, research_prompt
from research.session_store import session_store
from research.logger_config import logger
from telemetry import record_event

# Create router with /research_plan prefix
research_plan_router = APIRouter(
    prefix="/research_plan",
    tags=["research_plan"]
)

# v2 research planner constants
MAX_RETRY_COUNT = 3
MAX_SECTION_OVERLAP = 0.55
SECTION_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)

RESEARCH_PLANNER_SECTION_ORDER = [
    "research_purpose",
    "research_design",
    "research_method",
    "validity_evaluation",
    "expected_effects",
    "anticipated_results",
]
RESEARCH_PLANNER_SECTION_KEYS = frozenset(RESEARCH_PLANNER_SECTION_ORDER)

RESEARCH_PLANNER_SECTION_LABELS = {
    "research_purpose": "Research Purpose",
    "research_design": "Research Design",
    "research_method": "Research Method",
    "validity_evaluation": "Validity Evaluation",
    "expected_effects": "Expected Effects",
    "anticipated_results": "Anticipated Results",
}

RESEARCH_PLANNER_QUESTIONS_PER_SECTION = 2
RESEARCH_PLANNER_PIMO_CATEGORIES = ("P", "I", "M", "O")
RESEARCH_PLANNER_SECTION_PIMO_DEFAULTS = {
    "research_purpose": ("O", "P"),
    "research_design": ("P", "I"),
    "research_method": ("I", "M"),
    "validity_evaluation": ("M", "O"),
    "expected_effects": ("O", "M"),
    "anticipated_results": ("O", "P"),
}

RESEARCH_PLANNER_FALLBACK_QUESTIONS = {
    "research_purpose": [
        "이 연구에서 예측하려는 1차 결과지표(outcome)와 임상적 의의는 무엇인가요?",
        "연구의 핵심 가설은 무엇이며, 해당 outcome을 예측해야 하는 근거는 무엇인가요?",
    ],
    "research_design": [
        "대상 환자군(Patient)의 선정/제외 기준과 비교군 구성은 어떻게 설정하나요?",
        "연구 유형(후향/전향, 관찰/실험)과 추적 기간은 어떻게 설계하나요?",
    ],
    "research_method": [
        "입력 데이터(Input)로 사용할 변수, 수집 시점, 전처리 기준은 무엇인가요?",
        "데이터 품질 관리(결측치/이상치 처리, 정규화)는 어떻게 수행하나요?",
    ],
    "validity_evaluation": [
        "적용할 모델/방법(Model/Method)과 성능 검증 전략은 무엇인가요?",
        "내부/외부 검증 계획과 성능 비교 기준은 무엇인가요?",
    ],
    "expected_effects": [
        "예측 결과가 실제 진료나 연구 의사결정에 줄 기대 효과는 무엇인가요?",
        "모델 적용 시 임상 워크플로우 또는 자원 효율성에서 기대되는 변화는 무엇인가요?",
    ],
    "anticipated_results": [
        "주요 outcome에서 예상되는 결과 패턴과 해석 계획은 무엇인가요?",
        "예상과 다른 결과가 나올 경우의 해석 및 후속 분석 계획은 무엇인가요?",
    ],
}

DOCUMENT_SECTION_ORDER = RESEARCH_PLANNER_SECTION_ORDER
MAX_REFERENCE_PAPERS_FOR_DOC = 10
MAX_REFERENCE_ABSTRACT_CHARS = 1200


def _now_iso() -> str:
    return datetime.now(timezone("Asia/Seoul")).isoformat()


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        if not value:
            return ""
        return str(next(iter(value.values()))).strip()
    return str(value).strip()


def _normalize_pimo_category(value: Any) -> str:
    pimo = _to_text(value).upper()
    return pimo if pimo in RESEARCH_PLANNER_PIMO_CATEGORIES else ""


def _default_pimo_category(section_key: str, idx_in_section: int) -> str:
    defaults = RESEARCH_PLANNER_SECTION_PIMO_DEFAULTS.get(section_key, RESEARCH_PLANNER_PIMO_CATEGORIES)
    if not defaults:
        return "O"
    return defaults[idx_in_section % len(defaults)]


def _get_research_planner_section_prompts() -> "OrderedDict[str, str]":
    prompt_map = getattr(research_prompt, "research_planner_section_prompts", None)
    if isinstance(prompt_map, dict):
        ordered = OrderedDict()
        for key in RESEARCH_PLANNER_SECTION_ORDER:
            value = prompt_map.get(key)
            if value:
                ordered[key] = value
        if len(ordered) == len(RESEARCH_PLANNER_SECTION_ORDER):
            return ordered

    return OrderedDict([
        ("research_purpose", getattr(research_prompt, "리서치플래너_연구목적_PT", "")),
        ("research_design", getattr(research_prompt, "리서치플래너_연구설계_PT", "")),
        ("research_method", getattr(research_prompt, "리서치플래너_연구방법_PT", "")),
        ("validity_evaluation", getattr(research_prompt, "리서치플래너_유효성평가_PT", "")),
        ("expected_effects", getattr(research_prompt, "리서치플래너_기대효과_PT", "")),
        ("anticipated_results", getattr(research_prompt, "리서치플래너_예상결과_PT", "")),
    ])


def _normalize_topic_response(topic_raw: str, parsed: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not isinstance(parsed, dict):
        return {"topic_raw": topic_raw, "topic_refined": topic_raw, "topic_en": ""}

    topic_refined = _to_text(
        parsed.get("topic_refined")
        or parsed.get("modified_sentence")
        or parsed.get("refined_topic")
        or topic_raw
    )
    topic_en = _to_text(
        parsed.get("topic_en")
        or parsed.get("translated_sentence")
        or parsed.get("topic_english")
        or ""
    )

    return {"topic_raw": topic_raw, "topic_refined": topic_refined or topic_raw, "topic_en": topic_en}


def _normalize_questions_payload(parsed: Any) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    section_counts = {section_key: 0 for section_key in RESEARCH_PLANNER_SECTION_ORDER}

    def add_question(idx: int, question_text: str, target_section: str = "", pimo_category: str = ""):
        question_text = _to_text(question_text)
        if not question_text:
            return
        target = _to_text(target_section)
        if target not in RESEARCH_PLANNER_SECTION_KEYS:
            target = RESEARCH_PLANNER_SECTION_ORDER[idx % len(RESEARCH_PLANNER_SECTION_ORDER)]
        pimo = _normalize_pimo_category(pimo_category) or _default_pimo_category(target, section_counts[target])
        normalized.append({
            "question_id": f"Q{len(normalized) + 1}",
            "target_section": target,
            "pimo_category": pimo,
            "question": question_text,
        })
        section_counts[target] += 1

    if isinstance(parsed, dict):
        questions = parsed.get("questions")
        if isinstance(questions, list):
            for idx, item in enumerate(questions):
                if isinstance(item, dict):
                    add_question(
                        idx,
                        item.get("question", ""),
                        _to_text(item.get("target_section")),
                        _to_text(item.get("pimo_category")),
                    )
                else:
                    add_question(idx, str(item))
        else:
            subqueries = parsed.get("Subqueries")
            if isinstance(subqueries, dict):
                for idx, value in enumerate(subqueries.values()):
                    add_question(idx, value)
            else:
                dict_like_subqueries = {
                    k: v for k, v in parsed.items()
                    if str(k).lower().startswith("subquery")
                }
                if dict_like_subqueries:
                    for idx, value in enumerate(dict_like_subqueries.values()):
                        add_question(idx, value)

                sub_query_list = parsed.get("sub_queries")
                if isinstance(sub_query_list, list):
                    for idx, value in enumerate(sub_query_list):
                        add_question(idx, value)

    elif isinstance(parsed, list):
        for idx, item in enumerate(parsed):
            if isinstance(item, dict):
                add_question(
                    idx,
                    item.get("question", ""),
                    item.get("target_section", ""),
                    item.get("pimo_category", ""),
                )
            else:
                add_question(idx, str(item))

    return normalized


def _ensure_question_coverage(questions: List[Dict[str, str]]) -> List[Dict[str, str]]:
    section_items: Dict[str, List[Dict[str, str]]] = {
        section_key: [] for section_key in RESEARCH_PLANNER_SECTION_ORDER
    }

    for item in questions:
        section_key = _to_text(item.get("target_section"))
        question_text = _to_text(item.get("question"))
        if section_key in section_items and question_text:
            pimo_category = _normalize_pimo_category(item.get("pimo_category")) or _default_pimo_category(
                section_key,
                len(section_items[section_key]),
            )
            section_items[section_key].append({
                "target_section": section_key,
                "pimo_category": pimo_category,
                "question": question_text,
            })

    finalized: List[Dict[str, str]] = []
    for section_key in RESEARCH_PLANNER_SECTION_ORDER:
        selected: List[Dict[str, str]] = []
        seen_questions = set()

        for item in section_items[section_key]:
            normalized_question = _to_text(item.get("question")).lower()
            if not normalized_question or normalized_question in seen_questions:
                continue
            selected.append(item)
            seen_questions.add(normalized_question)
            if len(selected) >= RESEARCH_PLANNER_QUESTIONS_PER_SECTION:
                break

        fallback_candidates = RESEARCH_PLANNER_FALLBACK_QUESTIONS.get(section_key, [])
        for fallback in fallback_candidates:
            if len(selected) >= RESEARCH_PLANNER_QUESTIONS_PER_SECTION:
                break
            fallback_question = _to_text(fallback)
            normalized_fallback = fallback_question.lower()
            if not fallback_question or normalized_fallback in seen_questions:
                continue
            selected.append({
                "target_section": section_key,
                "pimo_category": _default_pimo_category(section_key, len(selected)),
                "question": fallback_question,
            })
            seen_questions.add(normalized_fallback)

        while len(selected) < RESEARCH_PLANNER_QUESTIONS_PER_SECTION:
            if PROMPT_LANG == "en":
                generic_question = (
                    f"Please provide an additional key question for {RESEARCH_PLANNER_SECTION_LABELS.get(section_key, section_key)}."
                )
            else:
                generic_question = f"{RESEARCH_PLANNER_SECTION_LABELS.get(section_key, section_key)} 관련 핵심 질문을 작성해주세요."
            normalized_generic = generic_question.lower()
            if normalized_generic in seen_questions:
                generic_question = (
                    f"{generic_question} (additional)"
                    if PROMPT_LANG == "en"
                    else f"{generic_question} (추가)"
                )
                normalized_generic = generic_question.lower()
            selected.append({
                "target_section": section_key,
                "pimo_category": _default_pimo_category(section_key, len(selected)),
                "question": generic_question,
            })
            seen_questions.add(normalized_generic)

        finalized.extend(selected[:RESEARCH_PLANNER_QUESTIONS_PER_SECTION])

    for idx, item in enumerate(finalized):
        item["question_id"] = f"Q{idx + 1}"

    return finalized


def _normalize_qa_pairs(qa_pairs: List[Any]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    section_counts = {section_key: 0 for section_key in RESEARCH_PLANNER_SECTION_ORDER}

    for idx, item in enumerate(qa_pairs):
        if isinstance(item, BaseModel):
            item_data = item.model_dump()
        else:
            item_data = item if isinstance(item, dict) else {}

        question = _to_text(item_data.get("question"))
        answer = _to_text(item_data.get("answer"))
        question_id = _to_text(item_data.get("question_id")) or f"Q{idx + 1}"
        target_section = _to_text(item_data.get("target_section"))

        if target_section not in RESEARCH_PLANNER_SECTION_KEYS:
            target_section = RESEARCH_PLANNER_SECTION_ORDER[idx % len(RESEARCH_PLANNER_SECTION_ORDER)]
        pimo_category = _normalize_pimo_category(item_data.get("pimo_category")) or _default_pimo_category(
            target_section,
            section_counts[target_section],
        )

        if not question:
            continue

        normalized.append({
            "question_id": question_id,
            "target_section": target_section,
            "pimo_category": pimo_category,
            "question": question,
            "answer": answer,
        })
        section_counts[target_section] += 1

    return normalized


def _build_qa_context(qa_pairs: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for item in qa_pairs:
        answer = _to_text(item.get("answer"))
        if not answer:
            continue
        pimo_category = _normalize_pimo_category(item.get("pimo_category"))
        pimo_suffix = f" / PIMO:{pimo_category}" if pimo_category else ""
        lines.append(
            f"[{item['question_id']}] ({item['target_section']}{pimo_suffix})\n"
            f"질문: {item['question']}\n"
            f"답변: {answer}"
        )
    return "\n\n".join(lines)


def _build_previous_sections_context(sections: Dict[str, str]) -> str:
    lines: List[str] = []
    for section_key in RESEARCH_PLANNER_SECTION_ORDER:
        section_text = _to_text(sections.get(section_key))
        if not section_text:
            continue
        section_label = RESEARCH_PLANNER_SECTION_LABELS.get(section_key, section_key)
        lines.append(f"[{section_label}]\n{section_text}")
    return "\n\n".join(lines)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _normalize_document_sections(
    planner_sections: Any,
    fallback_sections: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Normalize 6-section planner payload with optional legacy fallbacks."""
    normalized = {section_key: "" for section_key in DOCUMENT_SECTION_ORDER}

    if isinstance(planner_sections, dict):
        for section_key in DOCUMENT_SECTION_ORDER:
            normalized[section_key] = _to_text(planner_sections.get(section_key))

    if isinstance(fallback_sections, dict):
        for section_key in DOCUMENT_SECTION_ORDER:
            if not normalized[section_key]:
                normalized[section_key] = _to_text(fallback_sections.get(section_key))

    return normalized


def _build_document_sections_context(sections: Dict[str, str]) -> str:
    """Build prompt context text from the normalized 6 planner sections."""
    lines: List[str] = []
    for section_key in DOCUMENT_SECTION_ORDER:
        section_text = _to_text(sections.get(section_key))
        if not section_text:
            continue
        section_label = RESEARCH_PLANNER_SECTION_LABELS.get(section_key, section_key)
        lines.append(f"[{section_label}]\n{section_text}")
    return "\n\n".join(lines)


def _normalize_reference_papers(reference_papers: Any) -> List[Dict[str, Any]]:
    """Keep only top-scored reference papers and normalize key fields."""
    if not isinstance(reference_papers, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for item in reference_papers:
        if not isinstance(item, dict):
            continue

        title = _to_text(item.get("Title") or item.get("title"))
        abstract = _to_text(item.get("Abstract") or item.get("abstract"))
        if not title and not abstract:
            continue

        normalized.append({
            "pmid": _to_text(item.get("PMID") or item.get("pmid")),
            "title": title,
            "authors": _to_text(item.get("Authors") or item.get("authors")),
            "journal": _to_text(item.get("Journal") or item.get("journal")),
            "year": _to_text(item.get("Year") or item.get("year") or item.get("Publication Date")),
            "abstract": abstract,
            "score": _to_int(item.get("score"), 0),
            "rationale": _to_text(item.get("rationale")),
        })

    normalized.sort(key=lambda x: x.get("score", 0), reverse=True)
    return normalized[:MAX_REFERENCE_PAPERS_FOR_DOC]


def _build_reference_context(reference_papers: List[Dict[str, Any]]) -> str:
    """Create compact reference context for downstream document generation prompts."""
    lines: List[str] = []
    for idx, paper in enumerate(reference_papers[:MAX_REFERENCE_PAPERS_FOR_DOC], start=1):
        abstract = _to_text(paper.get("abstract"))
        if len(abstract) > MAX_REFERENCE_ABSTRACT_CHARS:
            abstract = abstract[:MAX_REFERENCE_ABSTRACT_CHARS] + "...(truncated)"

        lines.append(
            f"[Reference {idx}]\n"
            f"PMID: {_to_text(paper.get('pmid')) or 'N/A'}\n"
            f"Title: {_to_text(paper.get('title')) or 'N/A'}\n"
            f"Year: {_to_text(paper.get('year')) or 'N/A'}\n"
            f"Journal: {_to_text(paper.get('journal')) or 'N/A'}\n"
            f"Score: {_to_text(paper.get('score')) or 'N/A'}\n"
            f"Rationale: {_to_text(paper.get('rationale')) or 'N/A'}\n"
            f"Abstract: {abstract or 'N/A'}"
        )
    return "\n\n".join(lines)


def _token_set(text: str) -> set:
    return set(token.lower() for token in SECTION_TOKEN_PATTERN.findall(text) if len(token) > 1)


def _calculate_overlap_ratio(current_text: str, previous_text: str) -> float:
    current_tokens = _token_set(current_text)
    previous_tokens = _token_set(previous_text)

    if not current_tokens or not previous_tokens:
        return 0.0

    return len(current_tokens.intersection(previous_tokens)) / len(current_tokens)


async def _request_json(
    tag: str,
    system_prompt: str,
    user_prompt: str,
    required_key: Optional[str] = None,
) -> Dict[str, Any]:
    last_raw_response = ""
    diagnostics: List[Dict[str, Any]] = []

    for retry in range(MAX_RETRY_COUNT):
        response_text = await asyncio.to_thread(
            llm_manager.get_response,
            system_prompt,
            user_prompt,
            telemetry_operation=tag,
            telemetry_section=required_key,
            telemetry_attempt=retry + 1,
        )
        last_raw_response = response_text
        parsed = to_json(response_text)
        response_preview = _to_text(response_text)[:700]

        if not isinstance(parsed, dict):
            diagnostics.append({
                "attempt": retry + 1,
                "reason": "invalid_json",
                "response_preview": response_preview,
            })
            await record_event(
                "llm_validation_failed", phase=tag, section=required_key,
                attempt=retry + 1,
                metadata={"reason": "invalid_json", "section": required_key},
            )
            logger.warning(f"{tag} - JSON 파싱 실패, 재시도 {retry + 1}/{MAX_RETRY_COUNT}")
            continue

        if required_key and required_key not in parsed:
            if len(parsed) == 1:
                parsed = {required_key: next(iter(parsed.values()))}
            else:
                diagnostics.append({
                    "attempt": retry + 1,
                    "reason": f"missing_required_key:{required_key}",
                    "response_preview": response_preview,
                    "parsed_keys": list(parsed.keys()),
                })
                await record_event(
                    "llm_validation_failed", phase=tag, section=required_key,
                    attempt=retry + 1, metadata={
                        "reason": "missing_required_key",
                        "section": required_key,
                        "parsed_keys": list(parsed.keys()),
                    },
                )
                logger.warning(f"{tag} - required key '{required_key}' 없음, 재시도 {retry + 1}/{MAX_RETRY_COUNT}")
                continue

        return parsed

    logger.error(f"{tag} - JSON 응답 파싱 실패, last response: {last_raw_response}")
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "error": "Failed to parse LLM response as JSON",
            "tag": tag,
            "required_key": required_key,
            "last_raw_response": _to_text(last_raw_response)[:1200],
            "attempts": diagnostics,
        },
    )


async def _generate_chain_section(
    tag: str,
    section_key: str,
    system_prompt: str,
    user_prompt: str,
    previous_sections_context: str,
) -> str:
    for retry in range(MAX_RETRY_COUNT):
        parsed = await _request_json(
            tag=tag,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            required_key=section_key,
        )
        section_text = _to_text(parsed.get(section_key))
        if not section_text:
            await record_event(
                "section_quality_retry", phase=tag, section=section_key,
                attempt=retry + 1,
                metadata={"reason": "empty_section", "section": section_key},
            )
            logger.warning(f"{tag} - 빈 응답, 재시도 {retry + 1}/{MAX_RETRY_COUNT}")
            continue

        if previous_sections_context:
            overlap = _calculate_overlap_ratio(section_text, previous_sections_context)
            if overlap > MAX_SECTION_OVERLAP and retry < MAX_RETRY_COUNT - 1:
                await record_event(
                    "section_quality_retry", phase=tag, section=section_key,
                    attempt=retry + 1, metadata={
                        "reason": "section_overlap",
                        "section": section_key,
                        "overlap_ratio": round(overlap, 4),
                        "threshold": MAX_SECTION_OVERLAP,
                    },
                )
                logger.warning(
                    f"{tag} - 이전 섹션과 중복률 높음(overlap={overlap:.2f}), 재시도 {retry + 1}/{MAX_RETRY_COUNT}"
                )
                continue

        return section_text

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "error": "Failed to generate section with acceptable quality",
            "section_key": section_key,
            "tag": tag,
            "max_retry_count": MAX_RETRY_COUNT,
            "max_section_overlap": MAX_SECTION_OVERLAP,
        },
    )


def _raise_internal_http_error(tag: str, error: Exception):
    if isinstance(error, HTTPException):
        raise error

    error_type = type(error).__name__
    error_message = str(error)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "error": "Unhandled server error",
            "tag": tag,
            "type": error_type,
            "message": error_message,
        },
    )

class ResearchBackgroundQuestionData(BaseModel):
    user_code: str = 'user'
    irb_research_title: str = 'irb_research_title from IRB generation'
    irb_research_purpose: str = 'irb_research_purpose from IRB generation'
    irb_research_design: str = 'irb_research_design from IRB generation'
    planner_sections: Dict[str, str] = Field(default_factory=dict)
    reference_papers: List[Dict[str, Any]] = Field(default_factory=list)

@research_plan_router.post("/get_research_background_answer", summary="연구배경을 작성하기 위한 질문을 생산합니다.")
async def get_research_background_answer(item: ResearchBackgroundQuestionData = Body(...)):
    TAG = 'research_get_title_answer'
    logger.info(f"{TAG} - 시작")

    try:
        user_code = _to_text(item.user_code) or "user"
        title = (
            _to_text(item.irb_research_title)
            or _to_text(session_store.get_user_data(user_code, "rp_topic_refined", ""))
            or _to_text(session_store.get_user_data(user_code, "rp_topic_raw", ""))
            or _to_text(session_store.get_user_data(user_code, "연구과제명", ""))
        )

        sections = _normalize_document_sections(
            item.planner_sections,
            {
                "research_purpose": item.irb_research_purpose,
                "research_design": item.irb_research_design,
            },
        )
        references = _normalize_reference_papers(item.reference_papers)
        if not references:
            references = _normalize_reference_papers(
                session_store.get_user_data(user_code, "pubmed_reference_top10", [])
            )
        has_references = len(references) > 0
        sections_context = _build_document_sections_context(sections)
        reference_context = _build_reference_context(references)

        logger.debug(f"{TAG} - 사용자 코드: {user_code}")
        session_store.set_user_data(user_code, '연구과제명', title)
        session_store.set_user_data(user_code, 'IRB_연구목적', _to_text(item.irb_research_purpose))
        session_store.set_user_data(user_code, 'IRB_연구설계', _to_text(item.irb_research_design))
        session_store.set_user_data(user_code, 'rp_doc_sections', sections)
        session_store.set_user_data(user_code, 'rp_doc_reference_top10', references)

        # Use planner 6-section context and top references as primary sources for QA generation.
        sendPrompt = (
            f"<연구과제명>\n{title if title else '없음'}\n</연구과제명>\n\n"
            f"<리서치플래너_6개섹션>\n{sections_context if sections_context else '없음'}\n</리서치플래너_6개섹션>\n\n"
            f"<참고문헌_TOP10>\n{reference_context if reference_context else '없음'}\n</참고문헌_TOP10>\n"
        )

        logger.debug(f"{TAG} - LLM 응답 요청 중")
        result = await asyncio.to_thread(
            llm_manager.get_response, research_prompt.연구배경질문_PT, sendPrompt,
            telemetry_operation=TAG, telemetry_section="research_background_questions",
        )
        logger.debug(f"{TAG} - LLM 응답: {result[:200] if result else 'None'}...")

        parsed_result = to_json(result)
        if parsed_result is None:
            logger.error(f"{TAG} - JSON 파싱 실패: {result}")
            raise HTTPException(status_code=500, detail="Failed to parse LLM response as JSON")

        logger.info(f"{TAG} - 종료")
        return parsed_result
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        _raise_internal_http_error(TAG, e)

class ResearchBackgroundData(BaseModel):
    user_code: str = 'user'
    irb_research_title: str = 'irb_research_title from IRB generation'
    irb_research_purpose: str = 'irb_research_purpose from IRB generation'
    irb_research_design: str = 'irb_research_design from IRB generation'
    planner_sections: Dict[str, str] = Field(default_factory=dict)
    reference_papers: List[Dict[str, Any]] = Field(default_factory=list)
    background_sub_queries: Dict[str, str] = {
        "question_1": "answer_1",
        "question_2": "answer_2",
        "question_3": "answer_3",
    }

@research_plan_router.post("/get_background_build_answer", summary="데이터와 프롬프트를 통해 연구배경을 작성합니다")
async def get_background_build_answer(item: ResearchBackgroundData = Body(...)):
    TAG = 'get_background_build_answer'
    logger.info(f"{TAG} - 시작")

    try:
        user_code = _to_text(item.user_code) or "user"
        title = _to_text(item.irb_research_title)
        goal = _to_text(item.irb_research_purpose)
        architect = _to_text(item.irb_research_design)
        subquery_dict = item.background_sub_queries if isinstance(item.background_sub_queries, dict) else {}

        sections = _normalize_document_sections(
            item.planner_sections,
            {
                "research_purpose": goal,
                "research_design": architect,
            },
        )
        references = _normalize_reference_papers(item.reference_papers)
        if not references:
            references = _normalize_reference_papers(
                session_store.get_user_data(user_code, "pubmed_reference_top10", [])
            )
        has_references = len(references) > 0
        sections_context = _build_document_sections_context(sections)
        reference_context = _build_reference_context(references)
        
        logger.debug(f"{TAG} - 사용자 코드: {user_code}")
        logger.debug(f"{TAG} - 주제 저장 중")
        
        session_store.set_user_data(user_code, 'IRB_연구과제명', title)
        session_store.set_user_data(user_code, 'IRB_연구목적', goal)
        session_store.set_user_data(user_code, 'IRB_연구설계', architect)
        session_store.set_user_data(user_code, '연구배경질문_서브쿼리묶음', subquery_dict)
        session_store.set_user_data(user_code, 'rp_doc_sections', sections)
        session_store.set_user_data(user_code, 'rp_doc_reference_top10', references)
        
        qa_lines: List[str] = []
        for question, answer in subquery_dict.items():
            q = _to_text(question)
            a = _to_text(answer)
            if q or a:
                qa_lines.append(f"질문: {q}\n답변: {a}")

        qa_context = "\n\n".join(qa_lines) if qa_lines else "없음"
        if has_references:
            writing_guidance = (
                "1) 연구배경은 제공된 참고문헌 TOP10을 우선 근거로 작성하세요.\n"
                "2) 근거 문장을 작성할 때 가능한 경우 문장 끝에 [Reference n] 형태로 표기하세요. (n은 참고문헌 번호)\n"
                "3) 참고문헌에 없는 사실을 단정하지 말고, 불확실한 내용은 일반론으로만 기술하세요.\n"
            )
        else:
            writing_guidance = (
                "1) 참고문헌이 제공되지 않았으므로, 리서치플래너 6개 섹션과 질문답변을 기반으로 작성하세요.\n"
                "2) [Reference n] 표기는 사용하지 마세요.\n"
                "3) 단정적 표현은 피하고 검증 가능한 범위에서 서술하세요.\n"
            )
        sendPrompt = (
            f"<연구과제명>\n{title if title else '없음'}\n</연구과제명>\n\n"
            f"<리서치플래너_6개섹션>\n{sections_context if sections_context else '없음'}\n</리서치플래너_6개섹션>\n\n"
            f"<참고문헌_TOP10>\n{reference_context if reference_context else '없음'}\n</참고문헌_TOP10>\n\n"
            f"<질문답변>\n{qa_context}\n</질문답변>\n\n"
            "<작성지시>\n"
            f"{writing_guidance}"
            "</작성지시>\n"
        )

        logger.debug(f"{TAG} - LLM 응답 요청 중")
        result = await asyncio.to_thread(
            llm_manager.get_response, research_prompt.연구배경작성_PT, sendPrompt,
            telemetry_operation=TAG, telemetry_section="research_background",
        )

        logger.debug(f"{TAG} - LLM 응답: {result[:200] if result else 'None'}...")

        # Parse JSON from LLM response
        parsed_result = to_json(result)
        if parsed_result is None:
            logger.error(f"{TAG} - JSON 파싱 실패: {result}")
            raise HTTPException(status_code=500, detail="Failed to parse LLM response as JSON")
        session_store.set_user_data(user_code, '연구배경', parsed_result)
        session_store.set_user_data(user_code, 'rp_doc_background', parsed_result)

        logger.info(f"{TAG} - 종료")
        return parsed_result
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise

class ResearchHypothesisData(BaseModel):
    user_code: str = 'user'
    irb_research_title: str = 'irb_research_title from IRB generation'
    research_background: str = 'research_background from Research Plan'
    irb_research_purpose: str = 'irb_research_purpose from IRB generation'
    planner_sections: Dict[str, str] = Field(default_factory=dict)
    reference_papers: List[Dict[str, Any]] = Field(default_factory=list)

@research_plan_router.post("/get_hypothesis", summary="연구 가설을 작성합니다.")
async def get_hypothesis(item: ResearchHypothesisData = Body(...)):
    TAG = 'research_get_hypothesis'
    logger.info(f"{TAG} - 시작")

    try:
        user_code = _to_text(item.user_code) or "user"
        research_topic = _to_text(item.irb_research_title)
        research_purpose = _to_text(item.irb_research_purpose)
        research_background = _to_text(item.research_background)

        sections = _normalize_document_sections(
            item.planner_sections,
            {
                "research_purpose": research_purpose,
            },
        )
        references = _normalize_reference_papers(item.reference_papers)
        if not references:
            references = _normalize_reference_papers(
                session_store.get_user_data(user_code, "pubmed_reference_top10", [])
            )
        has_references = len(references) > 0
        sections_context = _build_document_sections_context(sections)
        reference_context = _build_reference_context(references)
        
        logger.debug(f"{TAG} - 사용자 코드: {user_code}")
        logger.debug(f"{TAG} - 연구 주제: {research_topic}")
        logger.debug(f"{TAG} - 연구 목적: {research_purpose}")  
        logger.debug(f"{TAG} - 연구 배경: {research_background}")
        session_store.set_user_data(user_code, 'rp_doc_sections', sections)
        session_store.set_user_data(user_code, 'rp_doc_reference_top10', references)
       
        if has_references:
            writing_guidance = (
                "1) 연구가설은 연구배경/리서치플래너 섹션/참고문헌 TOP10의 정합성을 우선 고려하세요.\n"
                "2) 근거가 있는 경우 [Reference n] 표기를 사용할 수 있습니다.\n"
                "3) 검증 가능하고 측정 가능한 형태로 간결하게 작성하세요.\n"
            )
        else:
            writing_guidance = (
                "1) 참고문헌이 없으므로 연구배경과 리서치플래너 섹션의 정합성에 집중해 작성하세요.\n"
                "2) [Reference n] 표기는 사용하지 마세요.\n"
                "3) 검증 가능하고 측정 가능한 형태로 간결하게 작성하세요.\n"
            )

        prompt = (
            f"<연구과제명>\n{research_topic if research_topic else '없음'}\n</연구과제명>\n\n"
            f"<연구목적>\n{research_purpose if research_purpose else '없음'}\n</연구목적>\n\n"
            f"<연구배경>\n{research_background if research_background else '없음'}\n</연구배경>\n\n"
            f"<리서치플래너_6개섹션>\n{sections_context if sections_context else '없음'}\n</리서치플래너_6개섹션>\n\n"
            f"<참고문헌_TOP10>\n{reference_context if reference_context else '없음'}\n</참고문헌_TOP10>\n\n"
            "<작성지시>\n"
            f"{writing_guidance}"
            "</작성지시>\n"
        )

        logger.debug(f"{TAG} - 연구 가설 작성 요청 중")
        result = await asyncio.to_thread(
            llm_manager.get_response, research_prompt.연구가설_PT, prompt,
            telemetry_operation=TAG, telemetry_section="research_hypothesis",
        )

        logger.debug(f"{TAG} - LLM 응답: {result[:200] if result else 'None'}...")

        # Parse JSON from LLM response
        parsed_result = to_json(result)
        if parsed_result is None:
            logger.error(f"{TAG} - JSON 파싱 실패: {result}")
            raise HTTPException(status_code=500, detail="Failed to parse LLM response as JSON")

        session_store.set_user_data(user_code, '연구가설', parsed_result)
        session_store.set_user_data(user_code, 'rp_doc_hypothesis', parsed_result)

        logger.info(f"{TAG} - 종료")
        return parsed_result
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise

class DataAnalysisQuestionData(BaseModel):
    user_code: str = 'user'
    irb_research_title: str = 'irb_research_title from IRB generation'
    irb_research_purpose: str = 'irb_research_purpose from IRB generation'
    irb_research_design: str = 'irb_research_design from IRB generation'
    irb_research_method: str = 'irb_research_method from IRB generation'
    irb_validity_evaluation: str = 'irb_validity_evaluation from IRB generation'
    planner_sections: Dict[str, str] = Field(default_factory=dict)
    reference_papers: List[Dict[str, Any]] = Field(default_factory=list)

@research_plan_router.post("/check_data_analysis", summary="데이터 분석 방법 작성을 위한 질문 생성")
async def check_data_analysis(item: DataAnalysisQuestionData = Body(...)):
    TAG = 'research_check_data_analysis'
    logger.info(f"{TAG} - 시작")

    try:
        user_code = _to_text(item.user_code) or "user"
        research_topic = _to_text(item.irb_research_title)
        research_purpose = _to_text(item.irb_research_purpose)
        research_architect = _to_text(item.irb_research_design)
        research_method = _to_text(item.irb_research_method)
        research_evaluation = _to_text(item.irb_validity_evaluation)

        sections = _normalize_document_sections(
            item.planner_sections,
            {
                "research_purpose": research_purpose,
                "research_design": research_architect,
                "research_method": research_method,
                "validity_evaluation": research_evaluation,
            },
        )
        references = _normalize_reference_papers(item.reference_papers)
        if not references:
            references = _normalize_reference_papers(
                session_store.get_user_data(user_code, "pubmed_reference_top10", [])
            )
        has_references = len(references) > 0
        sections_context = _build_document_sections_context(sections)
        reference_context = _build_reference_context(references)

        
        logger.debug(f"{TAG} - 사용자 코드: {user_code}")
        logger.debug(f"{TAG} - 연구 과제명: {research_topic}")
        logger.debug(f"{TAG} - 연구 목적: {research_purpose}")
        logger.debug(f"{TAG} - 연구 설계: {research_architect}")
        logger.debug(f"{TAG} - 연구 방법: {research_method}")
        logger.debug(f"{TAG} - 연구 유효성 평가: {research_evaluation}")
        
        session_store.set_user_data(user_code, 'rp_doc_sections', sections)
        session_store.set_user_data(user_code, 'rp_doc_reference_top10', references)
        
        prompt = (
            f"<연구과제명>\n{research_topic if research_topic else '없음'}\n</연구과제명>\n\n"
            f"<리서치플래너_6개섹션>\n{sections_context if sections_context else '없음'}\n</리서치플래너_6개섹션>\n\n"
            f"<참고문헌_TOP10>\n{reference_context if reference_context else '없음'}\n</참고문헌_TOP10>\n\n"
            "<지시사항>\n"
            "데이터 분석 및 활용 방법 문서 작성을 위해 추가 확인이 필요한 질문만 생성하세요.\n"
            "</지시사항>\n"
        )

        logger.debug(f"{TAG} - 데이터 분석 질문 생성 요청 중")
        result = await asyncio.to_thread(
            llm_manager.get_response, research_prompt.데이터분석_및_활용_방법_질문_PT, prompt,
            telemetry_operation=TAG, telemetry_section="data_analysis_questions",
        )

        logger.debug(f"{TAG} - LLM 응답: {result[:200] if result else 'None'}...")

        # Parse JSON from LLM response
        parsed_result = to_json(result)
        if parsed_result is None:
            logger.error(f"{TAG} - JSON 파싱 실패: {result}")
            raise HTTPException(status_code=500, detail="Failed to parse LLM response as JSON")

        logger.info(f"{TAG} - 종료")
        return parsed_result
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        raise


class DataAnalysisData(BaseModel):
    user_code: str = 'user'
    irb_research_title: str = 'irb_research_title from IRB generation'
    irb_research_purpose: str = 'irb_research_purpose from IRB generation'
    irb_research_design: str = 'irb_research_design from IRB generation'
    irb_research_method: str = 'irb_research_method from IRB generation'
    irb_validity_evaluation: str = 'irb_validity_evaluation from IRB generation'
    planner_sections: Dict[str, str] = Field(default_factory=dict)
    reference_papers: List[Dict[str, Any]] = Field(default_factory=list)
    data_analysis_sub_queries: Dict[str, str] = {
        "question_1": "answer_1",
        "question_2": "answer_2",
        "question_3": "answer_3",
    }


@research_plan_router.post("/get_data_analysis", summary="데이터 분석 방법 작성")
async def get_data_analysis(item: DataAnalysisData = Body(...)):
    TAG = 'research_get_data_analysis'
    logger.info(f"{TAG} - 시작")

    try:
        user_code = _to_text(item.user_code) or "user"
        research_topic = _to_text(item.irb_research_title)
        research_purpose = _to_text(item.irb_research_purpose)
        research_architect = _to_text(item.irb_research_design)
        research_method = _to_text(item.irb_research_method)
        research_evaluation = _to_text(item.irb_validity_evaluation)
        subquery_dict = item.data_analysis_sub_queries if isinstance(item.data_analysis_sub_queries, dict) else {}

        sections = _normalize_document_sections(
            item.planner_sections,
            {
                "research_purpose": research_purpose,
                "research_design": research_architect,
                "research_method": research_method,
                "validity_evaluation": research_evaluation,
            },
        )
        references = _normalize_reference_papers(item.reference_papers)
        if not references:
            references = _normalize_reference_papers(
                session_store.get_user_data(user_code, "pubmed_reference_top10", [])
            )
        has_references = len(references) > 0
        sections_context = _build_document_sections_context(sections)
        reference_context = _build_reference_context(references)
        
        logger.debug(f"{TAG} - 사용자 코드: {user_code}")
        logger.debug(f"{TAG} - 연구 과제명: {research_topic}")
        logger.debug(f"{TAG} - 연구 목적: {research_purpose}")
        logger.debug(f"{TAG} - 연구 설계: {research_architect}")
        logger.debug(f"{TAG} - 연구 방법: {research_method}")
        logger.debug(f"{TAG} - 연구 유효성 평가: {research_evaluation}")
        logger.debug(f"{TAG} - 서브쿼리 묶음: {subquery_dict}")
        
        session_store.set_user_data(user_code, '연구과제명', research_topic)
        session_store.set_user_data(user_code, '연구목적', research_purpose)
        session_store.set_user_data(user_code, '연구설계', research_architect)
        session_store.set_user_data(user_code, '연구방법', research_method)
        session_store.set_user_data(user_code, '연구유효성평가', research_evaluation)
        session_store.set_user_data(user_code, '데이터분석활용방법질문_서브쿼리묶음', subquery_dict)
        session_store.set_user_data(user_code, 'rp_doc_sections', sections)
        session_store.set_user_data(user_code, 'rp_doc_reference_top10', references)
        
        logger.debug(f"{TAG} - 연구 배경 질문 서브쿼리 묶음 처리 중")
        qa_lines: List[str] = []
        for question, answer in subquery_dict.items():
            q = _to_text(question)
            a = _to_text(answer)
            if q or a:
                qa_lines.append(f"질문: {q}\n답변: {a}")

        qa_context = "\n\n".join(qa_lines) if qa_lines else "없음"
        if has_references:
            writing_guidance = (
                "1) 데이터 분석 및 활용 방법은 제공된 참고문헌 TOP10의 근거를 우선 활용하세요.\n"
                "2) 근거 기반 서술에는 가능한 경우 [Reference n] 형태의 주석을 문장 끝에 표기하세요.\n"
                "3) 연구 계획서 문체를 유지하고, 숫자 목록이 아닌 자연스러운 문단으로 작성하세요.\n"
            )
        else:
            writing_guidance = (
                "1) 참고문헌이 제공되지 않았으므로 리서치플래너 6개 섹션과 질문답변을 중심으로 작성하세요.\n"
                "2) [Reference n] 표기는 사용하지 마세요.\n"
                "3) 연구 계획서 문체를 유지하고, 숫자 목록이 아닌 자연스러운 문단으로 작성하세요.\n"
            )
        prompt = (
            f"<연구과제명>\n{research_topic if research_topic else '없음'}\n</연구과제명>\n\n"
            f"<리서치플래너_6개섹션>\n{sections_context if sections_context else '없음'}\n</리서치플래너_6개섹션>\n\n"
            f"<참고문헌_TOP10>\n{reference_context if reference_context else '없음'}\n</참고문헌_TOP10>\n\n"
            f"<질문답변>\n{qa_context}\n</질문답변>\n\n"
            "<작성지시>\n"
            f"{writing_guidance}"
            "</작성지시>\n"
        )
        
        logger.debug(f"{TAG} - 연구 배경 질문 서브쿼리 묶음 처리 완료")

        logger.debug(f"{TAG} - 데이터 분석 방법 작성 요청 중")
        result = await asyncio.to_thread(
            llm_manager.get_response, research_prompt.데이터분석_및_활용_작성_PT, prompt,
            telemetry_operation=TAG, telemetry_section="data_analysis",
        )

        logger.debug(f"{TAG} - LLM 응답: {result[:200] if result else 'None'}...")

        # Parse JSON from LLM response
        parsed_result = to_json(result)
        if parsed_result is None:
            logger.error(f"{TAG} - JSON 파싱 실패: {result}")
            raise HTTPException(status_code=500, detail="Failed to parse LLM response as JSON")

        session_store.set_user_data(user_code, '데이터분석방법', parsed_result)
        session_store.set_user_data(user_code, 'rp_doc_data_analysis', parsed_result)

        logger.info(f"{TAG} - 종료")
        return parsed_result
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        _raise_internal_http_error(TAG, e)


RESEARCH_DOC_OUTPUT_KEYS = {
    "research_background": "research_background",
    "research_hypothesis": "research_hypothesis",
    "data_analysis_method": "analysis_utilization_method",
}

RESEARCH_DOC_STORAGE_KEYS = {
    "research_background": "연구배경",
    "research_hypothesis": "연구가설",
    "data_analysis_method": "데이터분석방법",
}

RESEARCH_DOC_RP_KEYS = {
    "research_background": "rp_doc_background",
    "research_hypothesis": "rp_doc_hypothesis",
    "data_analysis_method": "rp_doc_data_analysis",
}


def _extract_document_text(value: Any, preferred_key: str = "") -> str:
    if isinstance(value, dict):
        if preferred_key and preferred_key in value:
            return _to_text(value.get(preferred_key))
        if value:
            return _to_text(next(iter(value.values())))
        return ""
    return _to_text(value)


def _build_legacy_qa_context(user_code: str) -> str:
    lines: List[str] = []

    background_qas = session_store.get_user_data(user_code, "연구배경질문_서브쿼리묶음", {})
    if isinstance(background_qas, dict):
        for question, answer in background_qas.items():
            q = _to_text(question)
            a = _to_text(answer)
            if q or a:
                lines.append(f"[Background QA]\n질문: {q}\n답변: {a}")

    data_analysis_qas = session_store.get_user_data(user_code, "데이터분석활용방법질문_서브쿼리묶음", {})
    if isinstance(data_analysis_qas, dict):
        for question, answer in data_analysis_qas.items():
            q = _to_text(question)
            a = _to_text(answer)
            if q or a:
                lines.append(f"[Data Analysis QA]\n질문: {q}\n답변: {a}")

    return "\n\n".join(lines)


class PlannerDocRevisionData(BaseModel):
    user_code: str = "user"
    doc_type: str = "research_background"
    current_content: str = ""
    revision_request: str = "수정 요청"


@research_plan_router.post("/v2/docs/revise", summary="Research Planner v2: 문서를 수정합니다.")
async def research_planner_v2_revise_document(item: PlannerDocRevisionData = Body(...)):
    TAG = "research_planner_v2_revise_document"
    logger.info(f"{TAG} - 시작")

    doc_type = _to_text(item.doc_type)
    revision_request = _to_text(item.revision_request)
    if doc_type not in RESEARCH_DOC_OUTPUT_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"doc_type must be one of {list(RESEARCH_DOC_OUTPUT_KEYS.keys())}",
        )
    if not revision_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="revision_request must be provided",
        )

    output_key = RESEARCH_DOC_OUTPUT_KEYS[doc_type]
    storage_key = RESEARCH_DOC_STORAGE_KEYS[doc_type]
    rp_storage_key = RESEARCH_DOC_RP_KEYS[doc_type]

    current_text = _to_text(item.current_content)
    if not current_text:
        stored = session_store.get_user_data(item.user_code, storage_key, "")
        current_text = _extract_document_text(stored, output_key)
    if not current_text:
        stored_rp = session_store.get_user_data(item.user_code, rp_storage_key, "")
        current_text = _extract_document_text(stored_rp, output_key)
    if not current_text:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"document '{doc_type}' not found for user '{item.user_code}'",
        )

    topic = _to_text(session_store.get_user_data(item.user_code, "rp_topic_refined", ""))
    if not topic:
        topic = _to_text(session_store.get_user_data(item.user_code, "rp_topic_raw", ""))
    if not topic:
        topic = _to_text(session_store.get_user_data(item.user_code, "IRB_연구과제명", ""))
    if not topic:
        topic = _to_text(session_store.get_user_data(item.user_code, "연구과제명", ""))

    planner_sections = session_store.get_user_data(item.user_code, "rp_sections_v2", {})
    planner_sections_context = _build_previous_sections_context(
        planner_sections if isinstance(planner_sections, dict) else {}
    )

    legacy_qa_context = _build_legacy_qa_context(item.user_code)
    planner_qa_pairs = session_store.get_user_data(item.user_code, "rp_answers_v2", [])
    planner_qa_context = _build_qa_context(
        _normalize_qa_pairs(planner_qa_pairs if isinstance(planner_qa_pairs, list) else [])
    )
    qa_context = "\n\n".join([ctx for ctx in [planner_qa_context, legacy_qa_context] if ctx]).strip()

    revision_user_prompt = (
        f"<연구주제>\n{topic if topic else '없음'}\n</연구주제>\n\n"
        f"<수정대상섹션>\n{doc_type}\n</수정대상섹션>\n\n"
        f"<현재문단>\n{current_text}\n</현재문단>\n\n"
        f"<수정요청>\n{revision_request}\n</수정요청>\n\n"
        f"<질문답변>\n{qa_context if qa_context else '없음'}\n</질문답변>\n\n"
        f"<다른섹션>\n{planner_sections_context if planner_sections_context else '없음'}\n</다른섹션>"
    )

    try:
        parsed = await _request_json(
            tag=TAG,
            system_prompt=getattr(research_prompt, "리서치플래너_문항수정_PT", ""),
            user_prompt=revision_user_prompt,
            required_key="revised_answer",
        )
        revised_text = _to_text(parsed.get("revised_answer"))
        if not revised_text:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate revised document content",
            )

        payload = {output_key: revised_text}
        session_store.set_user_data(item.user_code, storage_key, payload)
        session_store.set_user_data(item.user_code, rp_storage_key, payload)
        session_store.set_user_data(item.user_code, "rp_status_v2", f"{doc_type}_revised")
        session_store.set_user_data(item.user_code, "rp_updated_at", _now_iso())

        logger.info(f"{TAG} - 종료")
        return {
            "doc_type": doc_type,
            "output_key": output_key,
            "revised_content": revised_text,
            "payload": payload,
        }
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        _raise_internal_http_error(TAG, e)


class PlannerTopicRefineData(BaseModel):
    user_code: str = "user"
    topic_raw: str = "연구 주제 원문"


class PlannerQuestionGenerateData(BaseModel):
    user_code: str = "user"
    topic: Optional[str] = None


class PlannerQuestionAnswerItem(BaseModel):
    question_id: str = "Q1"
    question: str = "질문"
    answer: str = ""
    target_section: str = "research_purpose"
    pimo_category: str = ""


class PlannerGenerateSectionsData(BaseModel):
    user_code: str = "user"
    topic: Optional[str] = None
    qa_pairs: List[PlannerQuestionAnswerItem] = Field(default_factory=list)


class PlannerSectionRevisionData(BaseModel):
    user_code: str = "user"
    section_key: str = "research_purpose"
    revision_request: str = "수정 요청"


@research_plan_router.post("/v2/topic/refine", summary="Research Planner v2: 주제를 정제합니다.")
async def research_planner_v2_refine_topic(item: PlannerTopicRefineData = Body(...)):
    TAG = "research_planner_v2_refine_topic"
    logger.info(f"{TAG} - 시작")

    topic_raw = _to_text(item.topic_raw)
    if not topic_raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="topic_raw must be provided",
        )

    try:
        warning_detail = None
        try:
            parsed = await _request_json(
                tag=TAG,
                system_prompt=getattr(research_prompt, "리서치플래너_주제정제_PT", ""),
                user_prompt=topic_raw,
            )
            result = _normalize_topic_response(topic_raw, parsed)
        except HTTPException as http_error:
            warning_detail = http_error.detail
            logger.warning(f"{TAG} - LLM refine 실패, fallback 사용: {warning_detail}")
            result = {
                "topic_raw": topic_raw,
                "topic_refined": topic_raw,
                "topic_en": "",
            }

        if warning_detail is not None:
            result["warning"] = {
                "message": "Refine failed, fallback to raw topic",
                "detail": warning_detail,
            }
        result["prompt_lang"] = PROMPT_LANG

        session_store.set_user_data(item.user_code, "rp_topic_raw", result["topic_raw"])
        session_store.set_user_data(item.user_code, "rp_topic_refined", result["topic_refined"])
        session_store.set_user_data(item.user_code, "rp_topic_en", result.get("topic_en", ""))
        session_store.set_user_data(item.user_code, "rp_status_v2", "topic_refined")
        session_store.set_user_data(item.user_code, "rp_updated_at", _now_iso())

        logger.info(f"{TAG} - 종료")
        return result
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        _raise_internal_http_error(TAG, e)


@research_plan_router.post("/v2/questions/generate", summary="Research Planner v2: 섹션 커버 질문을 생성합니다.")
async def research_planner_v2_generate_questions(item: PlannerQuestionGenerateData = Body(...)):
    TAG = "research_planner_v2_generate_questions"
    logger.info(f"{TAG} - 시작")

    topic = _to_text(item.topic) or _to_text(session_store.get_user_data(item.user_code, "rp_topic_refined", ""))
    if not topic:
        topic = _to_text(session_store.get_user_data(item.user_code, "rp_topic_raw", ""))

    if not topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="topic must be provided or refined topic must exist",
        )

    try:
        prompt_input = f"연구주제: {topic}"
        parsed = await _request_json(
            tag=TAG,
            system_prompt=getattr(research_prompt, "리서치플래너_질문생성_PT", ""),
            user_prompt=prompt_input,
        )

        questions = _normalize_questions_payload(parsed)
        questions = _ensure_question_coverage(questions)

        session_store.set_user_data(item.user_code, "rp_topic_refined", topic)
        session_store.set_user_data(item.user_code, "rp_questions_v2", questions)
        session_store.set_user_data(item.user_code, "rp_status_v2", "questions_generated")
        session_store.set_user_data(item.user_code, "rp_updated_at", _now_iso())

        logger.info(f"{TAG} - 종료")
        return {
            "topic": topic,
            "questions": questions,
            "required_sections": RESEARCH_PLANNER_SECTION_ORDER,
        }
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        _raise_internal_http_error(TAG, e)


@research_plan_router.post("/v2/sections/generate_chain", summary="Research Planner v2: 6개 섹션을 chain 방식으로 생성합니다.")
async def research_planner_v2_generate_sections(item: PlannerGenerateSectionsData = Body(...)):
    TAG = "research_planner_v2_generate_sections"
    logger.info(f"{TAG} - 시작")

    topic = _to_text(item.topic) or _to_text(session_store.get_user_data(item.user_code, "rp_topic_refined", ""))
    if not topic:
        topic = _to_text(session_store.get_user_data(item.user_code, "rp_topic_raw", ""))

    if not topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="topic must be provided",
        )

    normalized_qa_pairs = _normalize_qa_pairs(item.qa_pairs)
    answered_qa_pairs = [qa for qa in normalized_qa_pairs if _to_text(qa.get("answer"))]

    if not answered_qa_pairs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one answered qa_pair is required",
        )

    qa_context = _build_qa_context(answered_qa_pairs)
    if not qa_context:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="qa_pairs must include at least one non-empty answer",
        )

    try:
        section_prompts = _get_research_planner_section_prompts()
        generated_sections: Dict[str, str] = {}

        session_store.set_user_data(item.user_code, "rp_topic_refined", topic)
        session_store.set_user_data(item.user_code, "rp_answers_v2", answered_qa_pairs)
        session_store.set_user_data(item.user_code, "rp_status_v2", "sections_generating")
        session_store.set_user_data(item.user_code, "rp_updated_at", _now_iso())

        for section_key, section_prompt in section_prompts.items():
            section_tag = f"{TAG}_{section_key}"
            previous_sections_context = _build_previous_sections_context(generated_sections)
            previous_context_text = previous_sections_context if previous_sections_context else "없음"

            section_user_prompt = (
                f"<연구주제>\n{topic}\n</연구주제>\n\n"
                f"<질문답변>\n{qa_context}\n</질문답변>\n\n"
                f"<생성대상섹션>\n{section_key}\n</생성대상섹션>\n\n"
                f"<이전섹션>\n{previous_context_text}\n</이전섹션>"
            )

            section_text = await _generate_chain_section(
                tag=section_tag,
                section_key=section_key,
                system_prompt=section_prompt,
                user_prompt=section_user_prompt,
                previous_sections_context=previous_sections_context,
            )
            generated_sections[section_key] = section_text
            session_store.set_user_data(item.user_code, f"rp_section_{section_key}", section_text)

        result = {
            "topic": topic,
            "sections": generated_sections,
            "metadata": {
                "generated_at": _now_iso(),
                "section_order": RESEARCH_PLANNER_SECTION_ORDER,
                "max_retry_count": MAX_RETRY_COUNT,
                "max_section_overlap": MAX_SECTION_OVERLAP,
            },
        }

        session_store.set_user_data(item.user_code, "rp_sections_v2", generated_sections)
        session_store.set_user_data(item.user_code, "rp_status_v2", "sections_generated")
        session_store.set_user_data(item.user_code, "rp_updated_at", _now_iso())

        logger.info(f"{TAG} - 종료")
        return result
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        _raise_internal_http_error(TAG, e)


@research_plan_router.post("/v2/sections/revise", summary="Research Planner v2: 특정 섹션을 수정합니다.")
async def research_planner_v2_revise_section(item: PlannerSectionRevisionData = Body(...)):
    TAG = "research_planner_v2_revise_section"
    logger.info(f"{TAG} - 시작")

    section_key = _to_text(item.section_key)
    revision_request = _to_text(item.revision_request)
    if section_key not in RESEARCH_PLANNER_SECTION_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"section_key must be one of {list(RESEARCH_PLANNER_SECTION_ORDER)}",
        )
    if not revision_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="revision_request must be provided",
        )

    sections = session_store.get_user_data(item.user_code, "rp_sections_v2", {})
    if not isinstance(sections, dict) or section_key not in sections:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"section '{section_key}' not found for user '{item.user_code}'",
        )

    topic = _to_text(session_store.get_user_data(item.user_code, "rp_topic_refined", ""))
    if not topic:
        topic = _to_text(session_store.get_user_data(item.user_code, "rp_topic_raw", ""))
    qa_pairs = session_store.get_user_data(item.user_code, "rp_answers_v2", [])
    qa_context = _build_qa_context(_normalize_qa_pairs(qa_pairs if isinstance(qa_pairs, list) else []))

    current_section = _to_text(sections.get(section_key))
    previous_sections = {k: v for k, v in sections.items() if k != section_key}
    previous_sections_context = _build_previous_sections_context(previous_sections)

    revision_user_prompt = (
        f"<연구주제>\n{topic}\n</연구주제>\n\n"
        f"<수정대상섹션>\n{section_key}\n</수정대상섹션>\n\n"
        f"<현재문단>\n{current_section}\n</현재문단>\n\n"
        f"<수정요청>\n{revision_request}\n</수정요청>\n\n"
        f"<질문답변>\n{qa_context if qa_context else '없음'}\n</질문답변>\n\n"
        f"<다른섹션>\n{previous_sections_context if previous_sections_context else '없음'}\n</다른섹션>"
    )

    try:
        parsed = await _request_json(
            tag=TAG,
            system_prompt=getattr(research_prompt, "리서치플래너_문항수정_PT", ""),
            user_prompt=revision_user_prompt,
            required_key="revised_answer",
        )
        revised_text = _to_text(parsed.get("revised_answer"))
        if not revised_text:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate revised section content",
            )

        sections[section_key] = revised_text
        session_store.set_user_data(item.user_code, "rp_sections_v2", sections)
        session_store.set_user_data(item.user_code, f"rp_section_{section_key}", revised_text)
        session_store.set_user_data(item.user_code, "rp_status_v2", "section_revised")
        session_store.set_user_data(item.user_code, "rp_updated_at", _now_iso())

        logger.info(f"{TAG} - 종료")
        return {
            "section_key": section_key,
            "section_content": revised_text,
            "sections": sections,
        }
    except Exception as e:
        logger.error(f"{TAG} - 에러: {str(e)}")
        logger.error(f"{TAG} - 에러 상세: {traceback.format_exc()}")
        _raise_internal_http_error(TAG, e)


@research_plan_router.get("/v2/result/{user_code}", summary="Research Planner v2: 저장된 결과를 조회합니다.")
async def research_planner_v2_get_result(user_code: str):
    TAG = "research_planner_v2_get_result"
    logger.info(f"{TAG} - 시작")

    if not session_store.has_user(user_code):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"user '{user_code}' not found",
        )

    result = {
        "user_code": user_code,
        "prompt_lang": PROMPT_LANG,
        "topic_raw": session_store.get_user_data(user_code, "rp_topic_raw", ""),
        "topic_refined": session_store.get_user_data(user_code, "rp_topic_refined", ""),
        "topic_en": session_store.get_user_data(user_code, "rp_topic_en", ""),
        "questions": session_store.get_user_data(user_code, "rp_questions_v2", []),
        "qa_pairs": session_store.get_user_data(user_code, "rp_answers_v2", []),
        "sections": session_store.get_user_data(user_code, "rp_sections_v2", {}),
        "status": session_store.get_user_data(user_code, "rp_status_v2", "idle"),
        "updated_at": session_store.get_user_data(user_code, "rp_updated_at", ""),
    }

    logger.info(f"{TAG} - 종료")
    return result
