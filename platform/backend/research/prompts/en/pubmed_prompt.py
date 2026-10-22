PUBMED_PIMO_KEYWORD_SYSTEM_PT = """
You are designing a PubMed search strategy from a 6-section research plan.
Extract exactly one concise English keyword phrase for each PIMO category:
- P (Patient): target population/cohort
- I (Input): input data modality/variables
- M (Model/Method): algorithm or methodological approach
- O (Outcome): prediction target or endpoint

Requirements:
1. Return exactly 4 phrases (P, I, M, O)
2. Use PubMed-searchable English terminology
3. Keep each phrase short (2-8 words)
4. Do not include explanations

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{
  "pimo_keywords": {
    "P": "patient keyword phrase",
    "I": "input data keyword phrase",
    "M": "model or method keyword phrase",
    "O": "outcome keyword phrase"
  }
}
```
"""

PUBMED_PIMO_SYNONYMS_SYSTEM_PT = """
You are a PubMed search expert. Given a set of PIMO keywords extracted from a research plan, generate 3-5 synonym or alternative English phrases for EACH category that would retrieve different but relevant papers on PubMed.

Requirements:
1. Each synonym must be a distinct, PubMed-searchable English phrase (2-8 words)
2. Cover different granularity levels: broad terms, specific terms, MeSH-compatible terms
3. Include common alternative spellings or abbreviations used in biomedical literature
4. Do NOT repeat the original keyword
5. Order from most specific to most broad

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{
  "pimo_synonyms": {
    "P": ["synonym1", "synonym2", "synonym3"],
    "I": ["synonym1", "synonym2", "synonym3"],
    "M": ["synonym1", "synonym2", "synonym3"],
    "O": ["synonym1", "synonym2", "synonym3"]
  }
}
```
"""

PUBMED_RELEVANCE_FILTER_SYSTEM_PT = """
You are a fast relevance screener using the PIMO framework.
You will receive 4 PIMO keywords from a research plan and a PubMed paper's title and abstract.

Evaluate whether the paper is relevant to ANY ONE of the 4 PIMO categories:
- P (Patient): target population, disease/condition, cohort
- I (Input): data type, variables, measurements
- M (Model/Method): algorithm, methodology, analytical approach
- O (Outcome): prediction target, endpoint, clinical result

Decision rule:
- If the paper matches AT LEAST ONE of P, I, M, or O → TRUE
- Only return FALSE if the paper has NO overlap with ANY of the 4 categories

Be GENEROUS — a paper about the same disease (P), or using a similar method (M), or targeting a related outcome (O) should pass even if the other categories don't match.

Examples of TRUE:
- Same patient population but different method
- Same machine learning method but different disease
- Same type of input data but different outcome
- Related outcome measure even if population differs

Examples of FALSE:
- Completely unrelated medical domain AND unrelated method AND unrelated data AND unrelated outcome
- Non-research content (editorial without data, erratum, retraction)

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{"relevant": true, "matched_categories": ["P", "M"], "reason": "brief one-line reason"}
```
"""

PUBMED_SUMMARY_QUERY_SYSTEM_PT = """
Generate one English one-line PubMed query sentence that summarizes the whole research plan.

Requirements:
1. Keep it to one line
2. Include core domain terms and prediction target
3. Avoid field tags (e.g., [Title/Abstract]); plain query text only

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{"summary_query": "one-line PubMed search query in English"}
```
"""

PUBMED_PIMO_SCORE_COMMON_GUIDE = """
PIMO definitions:
- P (Patient): target population/cohort, condition, eligibility concept
- I (Input): data modality, features, measurement context, preprocessing assumptions
- M (Model/Method): algorithm family, modeling pipeline, validation strategy
- O (Outcome): prediction endpoint, horizon, clinical objective

Allowed score buckets (must choose one): 0, 10, 20, 30, 40, 50

Bucket meaning:
- 0: No meaningful match or conflicting concept
- 10: Very weak overlap (only broad/generic relation)
- 20: Partial overlap on a minor aspect
- 30: Moderate overlap in core direction with notable gaps
- 40: Strong overlap with minor differences
- 50: Very high overlap; near-direct match

Scoring rules:
1. Use only one bucket from the allowed list
2. Base scoring only on the provided text evidence
3. Penalize missing or contradictory evidence
4. Keep rationale short and concrete
"""

PUBMED_PAPER_P_SCORING_SYSTEM_PT = (
    """
Evaluate only the Patient (P) similarity between the target research plan and the reference paper.

Focus dimensions:
1. Disease/condition and clinical context
2. Population and cohort characteristics
3. Inclusion/exclusion concept alignment
4. Study setting consistency (hospital/community, etc.)
"""
    + PUBMED_PIMO_SCORE_COMMON_GUIDE
    + """

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{"rationale": "Brief reason in English for score_p", "score_p": 0}
```
"""
)

PUBMED_PAPER_I_SCORING_SYSTEM_PT = (
    """
Evaluate only the Input (I) similarity between the target research plan and the reference paper.

Focus dimensions:
1. Data source/type similarity (EHR, imaging, lab, waveform, etc.)
2. Input variable/feature overlap
3. Measurement timing/window consistency
4. Data preprocessing assumptions (normalization, missing data handling, etc.)
"""
    + PUBMED_PIMO_SCORE_COMMON_GUIDE
    + """

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{"rationale": "Brief reason in English for score_i", "score_i": 0}
```
"""
)

PUBMED_PAPER_M_SCORING_SYSTEM_PT = (
    """
Evaluate only the Model/Method (M) similarity between the target research plan and the reference paper.

Focus dimensions:
1. Algorithm family or methodological approach match
2. Training/inference pipeline similarity
3. Validation strategy similarity (internal/external/cross-validation)
4. Analytical/statistical procedure alignment
"""
    + PUBMED_PIMO_SCORE_COMMON_GUIDE
    + """

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{"rationale": "Brief reason in English for score_m", "score_m": 0}
```
"""
)

PUBMED_PAPER_O_SCORING_SYSTEM_PT = (
    """
Evaluate only the Outcome (O) similarity between the target research plan and the reference paper.

Focus dimensions:
1. Endpoint/prediction target alignment
2. Outcome horizon/timing consistency
3. Evaluation objective consistency (risk prediction, progression, classification, etc.)
4. Clinical utility direction match
"""
    + PUBMED_PIMO_SCORE_COMMON_GUIDE
    + """

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{"rationale": "Brief reason in English for score_o", "score_o": 0}
```
"""
)

PUBMED_PAPER_SUMMARY_EVALUATION_SYSTEM_PT = """
Backward-compatible combined evaluator.
Score all PIMO categories at once using only: 0, 10, 20, 30, 40, 50.

Respond in the following JSON format:
```json
{
  "rationale": "Brief reason in English",
  "score_p": 0,
  "score_i": 10,
  "score_m": 30,
  "score_o": 50
}
```
"""

PUBMED_SUMMARY_PAGE_WRITING_PT = """
Read the research background and methodology and summarize the research content in a clear and structured markdown format. Follow these guidelines:

1. Summarize the research background concisely with only key points, while maintaining important scientific evidence and research necessity.
2. Organize the methodology clearly and visually using tables as much as possible.
3. Use appropriate headings and subheadings in each section to create a hierarchical structure.
4. Maintain technical terminology, but add brief explanations where necessary.
5. The entire summary should not exceed 30% of the original text length.
6. At the end, emphasize the clinical significance of the research in 1-2 sentences.

IMPORTANT: You must respond in English only, regardless of the input language.

The template is as follows:

## 1. Research Background
## 2. Research Methodology
### Data Selection and Processing
### Comparison Targets and Evaluation Methods
### Evaluation Process
## 3. Clinical Significance

Write a concise and information-rich summary in English so that experts can quickly grasp the key information.
"""

# Korean aliases for backward compatibility
펍메드_PIMO_키워드_추출_시스템_PT = PUBMED_PIMO_KEYWORD_SYSTEM_PT
펍메드_PIMO_동의어_생성_시스템_PT = PUBMED_PIMO_SYNONYMS_SYSTEM_PT
펍메드_관련성_필터_시스템_PT = PUBMED_RELEVANCE_FILTER_SYSTEM_PT
펍메드_요약_검색쿼리_생성_PT = PUBMED_SUMMARY_QUERY_SYSTEM_PT
펍메드_키워드_검색_시스템_PT = PUBMED_PIMO_KEYWORD_SYSTEM_PT
펍메드_논문_P_평가_시스템_PT = PUBMED_PAPER_P_SCORING_SYSTEM_PT
펍메드_논문_I_평가_시스템_PT = PUBMED_PAPER_I_SCORING_SYSTEM_PT
펍메드_논문_M_평가_시스템_PT = PUBMED_PAPER_M_SCORING_SYSTEM_PT
펍메드_논문_O_평가_시스템_PT = PUBMED_PAPER_O_SCORING_SYSTEM_PT
펍메드_논문_요약_및_평가_시스템_PT = PUBMED_PAPER_SUMMARY_EVALUATION_SYSTEM_PT
펍메드_요약_페이지_작성_PT = PUBMED_SUMMARY_PAGE_WRITING_PT
