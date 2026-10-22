import asyncio
import itertools
import json
import re
import time
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from research import llm_manager
from research.logger_config import logger
from research.prompts import pubmed_prompt
from research.pubmed_manager import (
    generate_pubmed_search_url,
    get_pubmed_metadata,
    remove_think_tags,
    search_pubmed,
    to_json,
)
from research.session_store import session_store
from telemetry import record_event


pubmed_search_router = APIRouter(
    prefix="/pubmed_search",
    tags=["pubmed_search"],
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESEARCH_SECTION_ORDER = [
    "research_purpose",
    "research_design",
    "research_method",
    "validity_evaluation",
    "expected_effects",
    "anticipated_results",
]

RESEARCH_SECTION_LABELS = {
    "research_purpose": "Research Purpose",
    "research_design": "Research Design",
    "research_method": "Research Method",
    "validity_evaluation": "Validity Evaluation",
    "expected_effects": "Expected Effects",
    "anticipated_results": "Anticipated Results",
}

PIMO_ORDER = ("P", "I", "M", "O")
PIMO_SCORE_BUCKETS = (0, 10, 20, 30, 40, 50)
PIMO_SCORE_KEY_MAP = {category: f"score_{category.lower()}" for category in PIMO_ORDER}
PIMO_PROMPT_ATTR_MAP = {
    "P": "펍메드_논문_P_평가_시스템_PT",
    "I": "펍메드_논문_I_평가_시스템_PT",
    "M": "펍메드_논문_M_평가_시스템_PT",
    "O": "펍메드_논문_O_평가_시스템_PT",
}

PUBMED_SEARCH_START_YEAR = 2004
PUBMED_RESULTS_PER_QUERY = 15
PUBMED_MAX_COLLECT_PAPERS = 200
PUBMED_MAX_EVAL_PAPERS = 150
PUBMED_MAX_TERMS_PER_BLOCK = 14
PUBMED_API_DELAY = 0.35  # seconds between PubMed API calls (rate limit)

PIMO_SYNONYMS_PER_CATEGORY = 5  # max synonyms to use per PIMO category
LLM_FILTER_BATCH_SIZE = 10  # concurrent LLM filter calls


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class PubmedSearchData(BaseModel):
    user_code: str = "user"
    research_plan_background: str = "연구배경"
    research_plan_data_analysis_method: str = "연구데이터분석 및 활용 방법"
    research_plan_sections: Dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _clean_query_text(value: str) -> str:
    return re.sub(r"\s+", " ", _to_text(value)).strip()


def _extract_year(value: str) -> str:
    text = _to_text(value)
    match = re.search(r"(19|20)\d{2}", text)
    return match.group(0) if match else text


def _safe_to_json(raw: str) -> Dict[str, Any]:
    parsed = to_json(_to_text(raw))
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

def _normalize_sections(raw_sections: Dict[str, str], background: str, plan: str) -> Dict[str, str]:
    sections = {key: _to_text(raw_sections.get(key, "")) for key in RESEARCH_SECTION_ORDER}

    if not sections["research_purpose"]:
        sections["research_purpose"] = _to_text(background)
    if not sections["research_method"]:
        sections["research_method"] = _to_text(plan)
    if not sections["validity_evaluation"]:
        sections["validity_evaluation"] = _to_text(plan)

    return sections


def _build_sections_text(sections: Dict[str, str]) -> str:
    lines: List[str] = []
    for section_key in RESEARCH_SECTION_ORDER:
        section_value = _to_text(sections.get(section_key, ""))
        if not section_value:
            continue
        lines.append(f"[{RESEARCH_SECTION_LABELS.get(section_key, section_key)}]\n{section_value}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Keyword helpers
# ---------------------------------------------------------------------------

def _pick_keyword_candidate(primary: str, secondary: str, fallback: str) -> str:
    for candidate in (primary, secondary):
        candidate = _clean_query_text(candidate)
        if candidate:
            first_chunk = re.split(r"[\n.;:]", candidate)[0].strip()
            if re.search(r"[가-힣]", first_chunk):
                continue
            words = first_chunk.split()
            if len(words) > 8:
                first_chunk = " ".join(words[:8])
            if first_chunk:
                return first_chunk
    return fallback


def _default_pimo_keywords(sections: Dict[str, str]) -> Dict[str, str]:
    return {
        "P": _pick_keyword_candidate(
            sections.get("research_design", ""),
            sections.get("research_purpose", ""),
            "target patient cohort",
        ),
        "I": _pick_keyword_candidate(
            sections.get("research_method", ""),
            sections.get("research_design", ""),
            "clinical input variables",
        ),
        "M": _pick_keyword_candidate(
            sections.get("validity_evaluation", ""),
            sections.get("research_method", ""),
            "predictive modeling method",
        ),
        "O": _pick_keyword_candidate(
            sections.get("anticipated_results", ""),
            sections.get("expected_effects", ""),
            "clinical outcome prediction",
        ),
    }


def _normalize_pimo_keywords(parsed: Dict[str, Any], sections: Dict[str, str]) -> Dict[str, str]:
    defaults = _default_pimo_keywords(sections)
    keyword_dict = parsed.get("pimo_keywords") if isinstance(parsed.get("pimo_keywords"), dict) else {}

    normalized: Dict[str, str] = {}
    for key in PIMO_ORDER:
        value = _clean_query_text(keyword_dict.get(key) or parsed.get(key) or defaults[key])
        normalized[key] = value or defaults[key]

    return normalized


def _normalize_pimo_synonyms(
    parsed: Dict[str, Any],
    pimo_keywords: Dict[str, str],
) -> Dict[str, List[str]]:
    """Parse LLM synonym response and merge with original keywords."""
    raw_synonyms = parsed.get("pimo_synonyms") if isinstance(parsed.get("pimo_synonyms"), dict) else {}

    result: Dict[str, List[str]] = {}
    for key in PIMO_ORDER:
        original = pimo_keywords.get(key, "")
        candidates = [original] if original else []

        raw_list = raw_synonyms.get(key, [])
        if isinstance(raw_list, list):
            for item in raw_list:
                text = _clean_query_text(str(item))
                if text and text.lower() != original.lower() and text not in candidates:
                    candidates.append(text)

        result[key] = candidates[:PIMO_SYNONYMS_PER_CATEGORY + 1]  # original + synonyms

    return result


# ---------------------------------------------------------------------------
# Query deduplication
# ---------------------------------------------------------------------------

def _dedupe_keep_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    deduped: List[str] = []
    for value in values:
        text = _clean_query_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _normalize_query_token(value: str) -> str:
    token = _clean_query_text(value)
    token = token.replace("(", " ").replace(")", " ")
    token = re.sub(r"\[[^\]]+\]", "", token)
    token = token.strip(" \"'")
    token = _clean_query_text(token)
    return token


def _split_keyword_candidates(raw: str) -> List[str]:
    text = _normalize_query_token(raw)
    if not text:
        return []

    split_tokens = [text]
    split_tokens.extend(
        re.split(
            r"\s*(?:,|;|/|\band\b|\bor\b|\bwith\b|\busing\b|\bvia\b)\s*",
            text,
            flags=re.IGNORECASE,
        )
    )
    split_tokens.extend(re.split(r"\s{2,}", text))

    candidates: List[str] = []
    for token in split_tokens:
        token = _normalize_query_token(token)
        if not token:
            continue
        if len(token) < 3 and " " not in token:
            continue
        candidates.append(token)

    return _dedupe_keep_order(candidates)[:6]


# ---------------------------------------------------------------------------
# PubMed query building — synonym-based
# ---------------------------------------------------------------------------

def _to_tiab_clause(term: str) -> str:
    normalized = _normalize_query_token(term)
    if not normalized:
        return ""
    if "*" in normalized and " " in normalized:
        normalized = normalized.replace("*", "").strip()
        if not normalized:
            return ""
        return f"\"{normalized}\"[tiab]"
    if "*" in normalized:
        return f"{normalized}[tiab]"
    if " " in normalized:
        return f"\"{normalized}\"[tiab]"
    return f"{normalized}[tiab]"


def _build_category_block_from_synonyms(
    category: str,
    pimo_synonyms: Dict[str, List[str]],
) -> str:
    """Build a single OR-joined block for one PIMO category using all its synonyms."""
    clauses: List[str] = []
    synonyms = pimo_synonyms.get(category, [])

    for synonym in synonyms:
        for token in _split_keyword_candidates(synonym):
            clause = _to_tiab_clause(token)
            if clause:
                clauses.append(clause)

    deduped = _dedupe_keep_order(clauses)[:PUBMED_MAX_TERMS_PER_BLOCK]
    if not deduped:
        fallback = _to_tiab_clause(synonyms[0] if synonyms else "clinical")
        return f"({fallback})" if fallback else "(clinical[tiab])"

    return "(" + " OR ".join(deduped) + ")"


def _build_expanded_query_specs(
    pimo_synonyms: Dict[str, List[str]],
    summary_query: str,
) -> List[Dict[str, str]]:
    """Build an expanded set of queries from synonym combinations."""
    query_specs: List[Dict[str, str]] = []

    # --- Strategy 1: Full block queries (like before but with synonyms) ---
    blocks = {
        cat: _build_category_block_from_synonyms(cat, pimo_synonyms)
        for cat in PIMO_ORDER
    }

    # All PIMO pair combinations (6)
    for left, right in itertools.combinations(PIMO_ORDER, 2):
        query_specs.append({
            "query_name": f"BLOCK_{left}{right}",
            "query_type": "block_pair",
            "query_text": f"{blocks[left]} AND {blocks[right]}",
        })

    # Core & Broad
    query_specs.append({
        "query_name": "BLOCK_CORE",
        "query_type": "block_core",
        "query_text": f"{blocks['P']} AND {blocks['M']} AND {blocks['O']}",
    })
    query_specs.append({
        "query_name": "BLOCK_BROAD",
        "query_type": "block_broad",
        "query_text": f"{blocks['P']} AND ({blocks['I']} OR {blocks['M']}) AND {blocks['O']}",
    })

    # --- Strategy 2: Cross-synonym pair queries ---
    # Pick individual synonym terms and create targeted 2-term queries
    cross_pairs = [("P", "O"), ("P", "M"), ("I", "M"), ("I", "O"), ("M", "O")]
    for cat_a, cat_b in cross_pairs:
        syns_a = pimo_synonyms.get(cat_a, [])
        syns_b = pimo_synonyms.get(cat_b, [])
        # Create queries from individual synonym cross-products (limit combinations)
        pairs_generated = 0
        for sa in syns_a[:3]:
            for sb in syns_b[:3]:
                clause_a = _to_tiab_clause(_normalize_query_token(sa))
                clause_b = _to_tiab_clause(_normalize_query_token(sb))
                if clause_a and clause_b:
                    query_specs.append({
                        "query_name": f"CROSS_{cat_a}{cat_b}_{pairs_generated}",
                        "query_type": "cross_pair",
                        "query_text": f"{clause_a} AND {clause_b}",
                    })
                    pairs_generated += 1
                if pairs_generated >= 4:
                    break
            if pairs_generated >= 4:
                break

    # --- Strategy 3: Summary query ---
    summary_clauses = _dedupe_keep_order(
        [_to_tiab_clause(t) for t in _split_keyword_candidates(summary_query) if t]
    )[:10]
    if summary_clauses:
        query_specs.append({
            "query_name": "SUMMARY",
            "query_type": "summary",
            "query_text": "(" + " OR ".join(summary_clauses) + ")",
        })

    # --- Strategy 4: Individual synonym standalone queries ---
    # Each synonym on its own to catch papers the combinations miss
    for cat in PIMO_ORDER:
        for idx, syn in enumerate(pimo_synonyms.get(cat, [])[:3]):
            clause = _to_tiab_clause(_normalize_query_token(syn))
            if clause:
                query_specs.append({
                    "query_name": f"SINGLE_{cat}_{idx}",
                    "query_type": "single",
                    "query_text": clause,
                })

    return query_specs


# ---------------------------------------------------------------------------
# PMID collection & dedup
# ---------------------------------------------------------------------------

def _round_robin_unique(id_lists: List[List[str]], limit: int) -> List[str]:
    pointers = [0 for _ in id_lists]
    selected: List[str] = []
    seen: Set[str] = set()

    while len(selected) < limit:
        progressed = False
        for idx, id_list in enumerate(id_lists):
            while pointers[idx] < len(id_list) and id_list[pointers[idx]] in seen:
                pointers[idx] += 1

            if pointers[idx] >= len(id_list):
                continue

            pmid = id_list[pointers[idx]]
            pointers[idx] += 1
            progressed = True

            if pmid in seen:
                continue

            seen.add(pmid)
            selected.append(pmid)

            if len(selected) >= limit:
                break

        if not progressed:
            break

    return selected


# ---------------------------------------------------------------------------
# Rule-based filter
# ---------------------------------------------------------------------------

def _rule_based_filter(metadata: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Return (pass, reason). Only rejects clearly unusable papers."""
    if not isinstance(metadata, dict):
        return False, "metadata fetch failed"

    abstract = _to_text(metadata.get("Abstract", ""))
    title = _to_text(metadata.get("Title", ""))

    if not abstract and not title:
        return False, "no title and no abstract"
    if not abstract:
        return False, "no abstract"

    lower_title = title.lower()
    reject_patterns = ["erratum", "retraction", "corrigendum", "withdrawn"]
    for pattern in reject_patterns:
        if pattern in lower_title:
            return False, f"non-research content: {pattern}"

    return True, "passed"


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _bucketize_score(value: Any) -> int:
    try:
        numeric = int(float(value))
    except Exception:
        numeric = 0
    return min(PIMO_SCORE_BUCKETS, key=lambda bucket: abs(bucket - numeric))


async def _llm_response(
    system_prompt: str,
    user_prompt: str,
    *,
    operation: str,
    section: Optional[str] = None,
    attempt: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    return await asyncio.to_thread(
        llm_manager.get_response,
        system_prompt,
        user_prompt,
        telemetry_operation=operation,
        telemetry_section=section,
        telemetry_attempt=attempt,
        telemetry_metadata=metadata,
    )


# ---------------------------------------------------------------------------
# LLM relevance filter
# ---------------------------------------------------------------------------

async def _llm_relevance_filter(
    title: str,
    abstract: str,
    pimo_keywords: Dict[str, str],
    pmid: str,
) -> Tuple[bool, str]:
    """Return (relevant, reason) using PIMO-based LLM screening."""
    pimo_text = "\n".join(f"- {k}: {v}" for k, v in pimo_keywords.items())
    user_input = (
        f"<PIMOKeywords>\n{pimo_text}\n</PIMOKeywords>\n"
        f"<PubMedPaper>\n"
        f"Title: {title}\n"
        f"Abstract: {abstract}\n"
        f"</PubMedPaper>"
    )
    raw = await _llm_response(
        pubmed_prompt.펍메드_관련성_필터_시스템_PT,
        user_input,
        operation="pubmed.relevance_filter",
        section="PIMO",
        metadata={"pmid": pmid},
    )
    parsed = _safe_to_json(remove_think_tags(raw))
    relevant = parsed.get("relevant", True)  # default to True (inclusive)
    reason = _to_text(parsed.get("reason", ""))

    if isinstance(relevant, str):
        relevant = relevant.lower().strip() in ("true", "yes", "1")

    return bool(relevant), reason


# ---------------------------------------------------------------------------
# PIMO scoring
# ---------------------------------------------------------------------------

def _get_pimo_scoring_prompt(category: str) -> str:
    prompt_attr = PIMO_PROMPT_ATTR_MAP.get(category, "")
    if prompt_attr:
        prompt = _to_text(getattr(pubmed_prompt, prompt_attr, ""))
        if prompt:
            return prompt

    fallback_attr = f"PUBMED_PAPER_{category}_SCORING_SYSTEM_PT"
    prompt = _to_text(getattr(pubmed_prompt, fallback_attr, ""))
    if prompt:
        return prompt

    return _to_text(getattr(pubmed_prompt, "펍메드_논문_요약_및_평가_시스템_PT", ""))


async def _score_pimo_category(category: str, evaluation_input: str, pmid: str) -> Dict[str, Any]:
    score_key = PIMO_SCORE_KEY_MAP.get(category, f"score_{category.lower()}")
    prompt = _get_pimo_scoring_prompt(category)
    if not prompt:
        return {"category": category, "score": 0, "rationale": "", "score_key": score_key}

    raw_response = await _llm_response(
        prompt,
        evaluation_input,
        operation="pubmed.pimo_scoring",
        section=category,
        metadata={"pmid": pmid},
    )
    parsed = _safe_to_json(remove_think_tags(raw_response))
    score = _bucketize_score(parsed.get(score_key, 0))
    rationale = _to_text(parsed.get("rationale", ""))

    return {
        "category": category,
        "score": score,
        "rationale": rationale,
        "score_key": score_key,
    }


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

@pubmed_search_router.post("/", summary="Research plan 기반 PubMed 논문 검색 및 유사도 평가")
async def get_pubmed_search(item: PubmedSearchData = Body(...)):
    tag = "get_pubmed_search"
    logger.info(f"{tag} - 요청 시작")

    try:
        user_code = _to_text(item.user_code) or "user"
        background = _to_text(item.research_plan_background)
        plan = _to_text(item.research_plan_data_analysis_method)
        sections = _normalize_sections(item.research_plan_sections, background, plan)
        sections_text = _build_sections_text(sections)

        session_store.set_user_data(user_code, "연구계획서_연구데이터분석_및_활용방법", plan)
        session_store.set_user_data(user_code, "연구계획서_연구배경", background)
        session_store.set_user_data(user_code, "연구계획서_섹션", sections)

        async def answer_stream_generator():
            scored_papers: List[Dict[str, Any]] = []

            # ==============================================================
            # Phase 1: Research summary
            # ==============================================================
            summary_input = (
                f"<ResearchPlanSections>\n{sections_text}\n</ResearchPlanSections>\n"
                f"<ResearchBackground>\n{background}\n</ResearchBackground>\n"
                f"<ResearchMethod>\n{plan}\n</ResearchMethod>"
            )
            summary_response = await _llm_response(
                pubmed_prompt.펍메드_요약_페이지_작성_PT,
                summary_input,
                operation="pubmed.research_summary",
                section="summary",
            )
            summary_markdown = _to_text(summary_response)
            yield f"{summary_markdown}\n"

            # ==============================================================
            # Phase 2: PIMO keyword extraction
            # ==============================================================
            pimo_keyword_response = await _llm_response(
                pubmed_prompt.펍메드_PIMO_키워드_추출_시스템_PT,
                sections_text,
                operation="pubmed.keyword_extraction",
                section="PIMO",
            )
            pimo_keyword_parsed = _safe_to_json(remove_think_tags(pimo_keyword_response))
            pimo_keywords = _normalize_pimo_keywords(pimo_keyword_parsed, sections)

            query_info = " | ".join(f"{k}:{v}" for k, v in pimo_keywords.items())
            yield f"STATUS: PIMO keywords => {query_info}\n"

            # ==============================================================
            # Phase 3: PIMO synonym generation
            # ==============================================================
            synonym_input = (
                f"<ResearchPlanSections>\n{sections_text}\n</ResearchPlanSections>\n"
                f"<PIMOKeywords>\n{json.dumps(pimo_keywords, ensure_ascii=False)}\n</PIMOKeywords>"
            )
            synonym_response = await _llm_response(
                pubmed_prompt.펍메드_PIMO_동의어_생성_시스템_PT,
                synonym_input,
                operation="pubmed.synonym_generation",
                section="PIMO",
            )
            synonym_parsed = _safe_to_json(remove_think_tags(synonym_response))
            pimo_synonyms = _normalize_pimo_synonyms(synonym_parsed, pimo_keywords)

            for cat in PIMO_ORDER:
                yield f"STATUS: {cat} synonyms => {pimo_synonyms.get(cat, [])}\n"

            # ==============================================================
            # Phase 4: Summary query generation
            # ==============================================================
            summary_query_response = await _llm_response(
                pubmed_prompt.펍메드_요약_검색쿼리_생성_PT,
                summary_markdown,
                operation="pubmed.query_generation",
                section="summary_query",
            )
            summary_query_parsed = _safe_to_json(remove_think_tags(summary_query_response))
            summary_query = _clean_query_text(summary_query_parsed.get("summary_query", ""))
            if not summary_query:
                summary_query = _clean_query_text(
                    " ".join(pimo_keywords.get(cat, "") for cat in PIMO_ORDER)
                )

            # ==============================================================
            # Phase 5: Build expanded queries & search PubMed
            # ==============================================================
            query_specs = _build_expanded_query_specs(pimo_synonyms, summary_query)
            yield f"STATUS: Total search queries => {len(query_specs)}\n"

            query_id_lists: List[List[str]] = []
            pmid_sources: Dict[str, Set[str]] = {}
            total_raw_hits = 0

            for qi, query_spec in enumerate(query_specs):
                query_name = query_spec["query_name"]
                query_text = query_spec["query_text"]
                compact_query = _to_text(query_text).replace("\n", " ").strip()

                search_url = generate_pubmed_search_url(
                    term=query_text,
                    start_date=PUBMED_SEARCH_START_YEAR,
                    num_results=PUBMED_RESULTS_PER_QUERY,
                )
                # requests.get is synchronous; keep it off the ASGI event loop so
                # health probes and other users stay responsive during searches.
                ids = await asyncio.to_thread(search_pubmed, search_url)
                query_id_lists.append(ids)
                total_raw_hits += len(ids)

                for pmid in ids:
                    if pmid not in pmid_sources:
                        pmid_sources[pmid] = set()
                    pmid_sources[pmid].add(query_name)

                if (qi + 1) % 5 == 0 or qi == len(query_specs) - 1:
                    yield f"STATUS: Searched {qi + 1}/{len(query_specs)} queries, {len(pmid_sources)} unique PMIDs so far\n"

                # Rate limiting for NCBI E-Utilities
                await asyncio.sleep(PUBMED_API_DELAY)

            selected_pmids = _round_robin_unique(query_id_lists, PUBMED_MAX_COLLECT_PAPERS)
            await record_event(
                "phase_completed", phase="pubmed.search",
                metadata={
                    "query_count": len(query_specs),
                    "raw_hit_count": total_raw_hits,
                    "unique_pmid_count": len(selected_pmids),
                },
            )
            yield f"STATUS: Collected {total_raw_hits} raw hits => {len(selected_pmids)} unique papers for filtering\n"

            # ==============================================================
            # Phase 6: Fetch metadata & rule-based filter
            # ==============================================================
            metadata_map: Dict[str, Dict[str, Any]] = {}
            rule_passed_pmids: List[str] = []
            rule_rejected = 0

            for idx, pmid in enumerate(selected_pmids):
                try:
                    metadata = await asyncio.to_thread(get_pubmed_metadata, pmid)
                    passed, reason = _rule_based_filter(metadata)
                    if not passed:
                        rule_rejected += 1
                    else:
                        metadata_map[pmid] = metadata
                        rule_passed_pmids.append(pmid)
                except Exception as e:
                    logger.error(f"{tag} - metadata fetch error for {pmid}: {e}")
                    rule_rejected += 1

                if (idx + 1) % 20 == 0:
                    yield f"STATUS: Fetched metadata {idx + 1}/{len(selected_pmids)}, {len(rule_passed_pmids)} passed rule filter\n"
                # E-Utilities allows only a few requests per second without a
                # dedicated API key. Rate-limit each efetch, not each batch.
                await asyncio.sleep(PUBMED_API_DELAY)

            await record_event(
                "phase_completed", phase="pubmed.rule_filter",
                metadata={
                    "input_count": len(selected_pmids),
                    "passed_count": len(rule_passed_pmids),
                    "rejected_count": rule_rejected,
                },
            )
            yield f"STATUS: Rule-based filter => {len(rule_passed_pmids)} passed, {rule_rejected} rejected\n"

            # ==============================================================
            # Phase 7: LLM relevance filter (batched, PIMO-based)
            # ==============================================================
            llm_passed_pmids: List[str] = []
            llm_rejected = 0

            async def _check_relevance(pmid: str) -> Tuple[str, bool, str]:
                md = metadata_map[pmid]
                title = _to_text(md.get("Title", ""))
                abstract = _to_text(md.get("Abstract", ""))
                relevant, reason = await _llm_relevance_filter(
                    title, abstract, pimo_keywords, pmid
                )
                return pmid, relevant, reason

            # Process in batches
            for batch_start in range(0, len(rule_passed_pmids), LLM_FILTER_BATCH_SIZE):
                batch = rule_passed_pmids[batch_start:batch_start + LLM_FILTER_BATCH_SIZE]
                tasks = [_check_relevance(pmid) for pmid in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"{tag} - LLM filter error: {result}")
                        # On error, include the paper (inclusive approach)
                        llm_passed_pmids.append(batch[0] if batch else "")
                        continue
                    pmid, relevant, reason = result
                    if relevant:
                        llm_passed_pmids.append(pmid)
                    else:
                        llm_rejected += 1

                processed = min(batch_start + LLM_FILTER_BATCH_SIZE, len(rule_passed_pmids))
                yield f"STATUS: LLM filter {processed}/{len(rule_passed_pmids)}, {len(llm_passed_pmids)} relevant so far\n"

            # Cap at max eval papers
            eval_pmids = llm_passed_pmids[:PUBMED_MAX_EVAL_PAPERS]
            await record_event(
                "phase_completed", phase="pubmed.relevance_filter",
                metadata={
                    "input_count": len(rule_passed_pmids),
                    "passed_count": len(llm_passed_pmids),
                    "rejected_count": llm_rejected,
                    "evaluation_count": len(eval_pmids),
                },
            )
            yield f"STATUS: LLM filter => {len(llm_passed_pmids)} passed, {llm_rejected} rejected. Evaluating {len(eval_pmids)} papers.\n"

            # ==============================================================
            # Phase 8: PIMO scoring (4 calls per paper, concurrent per paper)
            # ==============================================================
            for idx, pmid in enumerate(eval_pmids):
                try:
                    yield f"STATUS: Scoring paper {idx + 1}/{len(eval_pmids)}\n"
                    paper_metadata = metadata_map[pmid]

                    abstract = _to_text(paper_metadata.get("Abstract", ""))
                    title = _to_text(paper_metadata.get("Title", ""))
                    matched_queries = sorted(list(pmid_sources.get(pmid, set())))

                    evaluation_input = (
                        f"<ResearchPlanSections>\n{sections_text}\n</ResearchPlanSections>\n"
                        f"<PIMOKeywords>\n{json.dumps(pimo_keywords, ensure_ascii=False)}\n</PIMOKeywords>\n"
                        f"<PubMedPaper>\n"
                        f"Title: {title}\n"
                        f"Abstract: {abstract}\n"
                        f"</PubMedPaper>"
                    )

                    category_tasks = [
                        _score_pimo_category(category, evaluation_input, pmid)
                        for category in PIMO_ORDER
                    ]
                    category_results = await asyncio.gather(
                        *category_tasks,
                        return_exceptions=True,
                    )

                    scores = {category: 0 for category in PIMO_ORDER}
                    rationales = {category: "" for category in PIMO_ORDER}
                    for category, result in zip(PIMO_ORDER, category_results):
                        if isinstance(result, Exception):
                            logger.error(f"{tag} - {category} 평가 실패: {result}")
                            continue
                        scores[category] = _bucketize_score(result.get("score", 0))
                        rationales[category] = _to_text(result.get("rationale", ""))

                    score_p = scores["P"]
                    score_i = scores["I"]
                    score_m = scores["M"]
                    score_o = scores["O"]
                    total_score = score_p + score_i + score_m + score_o

                    paper_metadata["Year"] = _extract_year(
                        paper_metadata.get("Publication Date", "")
                    )
                    paper_metadata["matched_queries"] = matched_queries
                    paper_metadata["pimo_keywords"] = pimo_keywords
                    paper_metadata["rationale_p"] = rationales["P"]
                    paper_metadata["rationale_i"] = rationales["I"]
                    paper_metadata["rationale_m"] = rationales["M"]
                    paper_metadata["rationale_o"] = rationales["O"]
                    paper_metadata["rationale"] = "\n".join(
                        line for line in [
                            f"P: {rationales['P']}".strip() if rationales["P"] else "",
                            f"I: {rationales['I']}".strip() if rationales["I"] else "",
                            f"M: {rationales['M']}".strip() if rationales["M"] else "",
                            f"O: {rationales['O']}".strip() if rationales["O"] else "",
                        ]
                        if line
                    )
                    paper_metadata["score_p"] = score_p
                    paper_metadata["score_i"] = score_i
                    paper_metadata["score_m"] = score_m
                    paper_metadata["score_o"] = score_o
                    paper_metadata["score"] = total_score

                    scored_papers.append(dict(paper_metadata))
                    yield json.dumps(paper_metadata, ensure_ascii=False) + "\n"
                except Exception as paper_error:
                    logger.error(f"{tag} - 논문 처리 중 에러: {paper_error}")
                    logger.error(traceback.format_exc())
                    continue

            # ==============================================================
            # Phase 9: Save results
            # ==============================================================
            scored_papers.sort(
                key=lambda paper: _bucketize_score(paper.get("score", 0)),
                reverse=True,
            )
            session_store.set_user_data(user_code, "pubmed_scored_papers", scored_papers)
            session_store.set_user_data(user_code, "pubmed_reference_top10", scored_papers[:10])
            await record_event(
                "phase_completed", phase="pubmed.pimo_scoring",
                metadata={
                    "paper_count": len(scored_papers),
                    "llm_call_target_count": len(eval_pmids) * len(PIMO_ORDER),
                    "top_reference_count": min(10, len(scored_papers)),
                },
            )

            yield f"STATUS: 완료 — 총 {len(scored_papers)}편 평가, 상위 10편 저장\n"
            yield "STATUS: 모든 데이터가 전송되었습니다\n"

        return StreamingResponse(
            answer_stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
    except Exception as error:
        logger.error(f"{tag} - 에러 발생: {str(error)}")
        logger.error(f"{tag} - 에러 상세: {traceback.format_exc()}")
        raise
