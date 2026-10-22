"""Read-only snapshot of a user's research session.

The frontend calls this once when it loads (or when the user code changes)
to restore the Planner, PubMed and Document tabs from server-side state.
Every generating endpoint already writes to the session store, so this is
the only endpoint needed to make results survive a page refresh.
"""

from typing import Any, Dict

from fastapi import APIRouter

from research.prompts import PROMPT_LANG
from research.session_store import session_store

session_router = APIRouter(prefix="/session", tags=["session"])


def _text(value: Any, preferred_key: str = "") -> str:
    """LLM document results are stored as {key: text}; unwrap to plain text."""
    if isinstance(value, dict):
        if preferred_key and preferred_key in value:
            return str(value.get(preferred_key) or "")
        return str(next(iter(value.values()), "") or "") if value else ""
    return "" if value is None else str(value)


@session_router.get("/{user_code}", summary="사용자 세션 전체 스냅샷을 반환합니다")
async def get_session(user_code: str) -> Dict[str, Any]:
    get = lambda key, default=None: session_store.get_user_data(user_code, key, default)  # noqa: E731
    return {
        "user_code": user_code,
        "exists": session_store.has_user(user_code),
        "prompt_lang": PROMPT_LANG,
        "planner": {
            "topic_raw": get("rp_topic_raw", ""),
            "topic_refined": get("rp_topic_refined", ""),
            "topic_en": get("rp_topic_en", ""),
            "questions": get("rp_questions_v2", []),
            "qa_pairs": get("rp_answers_v2", []),
            "sections": get("rp_sections_v2", {}),
            "status": get("rp_status_v2", "idle"),
            "updated_at": get("rp_updated_at", ""),
        },
        "pubmed": {
            "papers": get("pubmed_scored_papers", []),
            "top_references": get("pubmed_reference_top10", []),
        },
        "document": {
            "background": _text(get("rp_doc_background"), "research_background"),
            "data_analysis": _text(get("rp_doc_data_analysis"), "analysis_utilization_method"),
            "hypothesis": _text(get("rp_doc_hypothesis"), "research_hypothesis"),
        },
    }
