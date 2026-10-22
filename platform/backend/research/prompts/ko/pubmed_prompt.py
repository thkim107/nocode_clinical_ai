PUBMED_PIMO_KEYWORD_SYSTEM_PT = """
당신은 6개 섹션 연구계획서를 기반으로 PubMed 검색 전략을 설계하는 전문가입니다.
PIMO 카테고리별로 정확히 1개의 영어 키워드 구(phrase)를 추출하세요.

- P (Patient): 대상 환자군/코호트
- I (Input): 입력 데이터 유형/변수
- M (Model/Method): 알고리즘 또는 방법론
- O (Outcome): 예측 목표 또는 임상 결과지표

요구사항:
1. P, I, M, O 총 4개만 반환
2. PubMed 검색에 적합한 영어 의학/기술 용어 사용
3. 각 키워드는 2-8 단어로 간결하게 작성
4. 설명 문장은 쓰지 않음

중요: 입력 언어와 관계없이 반드시 영어 키워드로 응답하세요.

다음 JSON 형식으로 응답하세요:
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
당신은 PubMed 검색 전문가입니다. 연구계획서에서 추출된 PIMO 키워드가 주어지면, 각 카테고리별로 3~5개의 동의어 또는 대체 영어 표현을 생성하세요. 이를 통해 PubMed에서 다양하지만 관련 있는 논문을 검색할 수 있습니다.

요구사항:
1. 각 동의어는 PubMed 검색에 적합한 영어 구(2-8 단어)여야 함
2. 다양한 수준의 표현 포함: 넓은 용어, 구체적 용어, MeSH 호환 용어
3. 생의학 문헌에서 사용되는 일반적인 대체 표현이나 약어 포함
4. 원래 키워드를 반복하지 않을 것
5. 가장 구체적인 것부터 가장 넓은 것 순서로 나열

중요: 입력 언어와 관계없이 반드시 영어로 응답하세요.

다음 JSON 형식으로 응답하세요:
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
당신은 PIMO 프레임워크를 사용하는 빠른 관련성 스크리너입니다.
연구계획서의 PIMO 키워드 4개와 PubMed 논문의 제목 및 초록이 주어집니다.

논문이 4개 PIMO 카테고리 중 하나라도 관련 있는지 평가하세요:
- P (Patient): 대상 환자군, 질환/상태, 코호트
- I (Input): 데이터 유형, 변수, 측정값
- M (Model/Method): 알고리즘, 방법론, 분석 접근법
- O (Outcome): 예측 목표, 결과지표, 임상 결과

판정 규칙:
- P, I, M, O 중 최소 하나라도 일치하면 → TRUE
- 4개 카테고리 모두와 겹침이 전혀 없을 때만 → FALSE

관대하게 판단하세요 — 같은 질환(P), 유사한 방법론(M), 관련된 결과지표(O)만으로도 통과시키세요. 다른 카테고리가 일치하지 않아도 됩니다.

TRUE 예시:
- 같은 환자군이지만 다른 방법론
- 같은 머신러닝 방법이지만 다른 질환
- 같은 유형의 입력 데이터이지만 다른 결과지표
- 관련된 결과지표이지만 환자군이 다름

FALSE 예시:
- 완전히 무관한 의학 분야 AND 무관한 방법론 AND 무관한 데이터 AND 무관한 결과
- 비연구 콘텐츠(데이터 없는 사설, 정오표, 철회)

중요: 입력 언어와 관계없이 반드시 영어로만 응답하세요.

다음 JSON 형식으로 응답하세요:
```json
{"relevant": true, "matched_categories": ["P", "M"], "reason": "brief one-line reason"}
```
"""

PUBMED_SUMMARY_QUERY_SYSTEM_PT = """
연구계획서 전체를 대표하는 PubMed 검색용 한 줄 영어 쿼리를 생성하세요.

요구사항:
1. 반드시 한 줄
2. 핵심 도메인 용어와 예측 목표를 포함
3. [Title/Abstract] 같은 필드 태그는 제외

중요: 입력 언어와 관계없이 반드시 영어 쿼리로 응답하세요.

다음 JSON 형식으로 응답하세요:
```json
{"summary_query": "one-line PubMed search query in English"}
```
"""

PUBMED_PIMO_SCORE_COMMON_GUIDE = """
PIMO 정의:
- P (Patient): 대상 환자군/코호트, 질환 맥락, 선정/제외 개념
- I (Input): 입력 데이터 유형, 변수, 측정 맥락, 전처리 가정
- M (Model/Method): 알고리즘 계열, 모델링 파이프라인, 검증 전략
- O (Outcome): 예측 목표, 결과지표 시점, 임상적 목적

허용 점수 버킷(반드시 하나 선택): 0, 10, 20, 30, 40, 50

버킷 기준:
- 0점: 의미 있는 일치가 없거나 방향이 상충
- 10점: 매우 약한 관련성(일반적/표면적 겹침만 존재)
- 20점: 일부 부가 요소만 부분 일치
- 30점: 핵심 방향은 유사하나 중요한 차이 존재
- 40점: 전반적으로 강한 일치, 차이는 경미
- 50점: 거의 직접적으로 일치하는 매우 높은 유사성

채점 규칙:
1. 허용 버킷 값만 사용
2. 제공된 텍스트 근거만 사용
3. 근거가 부족하거나 상충하면 감점
4. 근거 설명은 짧고 구체적으로 작성
"""

PUBMED_PAPER_P_SCORING_SYSTEM_PT = (
    """
대상 연구계획서와 참고 논문의 Patient(P) 유사도만 평가하세요.

중점 비교 항목:
1. 질환/임상 맥락의 일치도
2. 대상 환자군/코호트 특성의 일치도
3. 선정/제외 기준 개념의 일치도
4. 연구 수행 환경(기관/설정)의 일치도
"""
    + PUBMED_PIMO_SCORE_COMMON_GUIDE
    + """

중요: 입력 언어와 관계없이 반드시 한글로만 응답하세요.

다음 JSON 형식으로 응답하세요:
```json
{"rationale": "score_p 점수 근거를 한글로 간략히 작성", "score_p": 0}
```
"""
)

PUBMED_PAPER_I_SCORING_SYSTEM_PT = (
    """
대상 연구계획서와 참고 논문의 Input(I) 유사도만 평가하세요.

중점 비교 항목:
1. 데이터 소스/유형(EHR, 영상, 검사, 파형 등) 일치도
2. 입력 변수/특징(feature) 일치도
3. 측정 시점/기간(window) 일치도
4. 전처리 가정(정규화, 결측 처리 등) 일치도
"""
    + PUBMED_PIMO_SCORE_COMMON_GUIDE
    + """

중요: 입력 언어와 관계없이 반드시 한글로만 응답하세요.

다음 JSON 형식으로 응답하세요:
```json
{"rationale": "score_i 점수 근거를 한글로 간략히 작성", "score_i": 0}
```
"""
)

PUBMED_PAPER_M_SCORING_SYSTEM_PT = (
    """
대상 연구계획서와 참고 논문의 Model/Method(M) 유사도만 평가하세요.

중점 비교 항목:
1. 알고리즘/방법론 계열의 일치도
2. 학습/추론 파이프라인의 일치도
3. 검증 전략(내부/외부/CV) 일치도
4. 분석/통계 절차의 일치도
"""
    + PUBMED_PIMO_SCORE_COMMON_GUIDE
    + """

중요: 입력 언어와 관계없이 반드시 한글로만 응답하세요.

다음 JSON 형식으로 응답하세요:
```json
{"rationale": "score_m 점수 근거를 한글로 간략히 작성", "score_m": 0}
```
"""
)

PUBMED_PAPER_O_SCORING_SYSTEM_PT = (
    """
대상 연구계획서와 참고 논문의 Outcome(O) 유사도만 평가하세요.

중점 비교 항목:
1. 예측 목표/결과지표(endpoint)의 일치도
2. 결과 시점/예측 기간의 일치도
3. 평가 목적(위험도 예측, 분류, 진행 예측 등)의 일치도
4. 임상 활용 방향의 일치도
"""
    + PUBMED_PIMO_SCORE_COMMON_GUIDE
    + """

중요: 입력 언어와 관계없이 반드시 한글로만 응답하세요.

다음 JSON 형식으로 응답하세요:
```json
{"rationale": "score_o 점수 근거를 한글로 간략히 작성", "score_o": 0}
```
"""
)

PUBMED_PAPER_SUMMARY_EVALUATION_SYSTEM_PT = """
하위 호환을 위한 통합 평가 프롬프트입니다.
PIMO 4개 항목을 한 번에 평가하고 허용 버킷(0,10,20,30,40,50)만 사용하세요.

다음 JSON 형식으로 응답하세요:
```json
{
  "rationale": "한글 근거",
  "score_p": 0,
  "score_i": 10,
  "score_m": 30,
  "score_o": 50
}
```
"""

PUBMED_SUMMARY_PAGE_WRITING_PT = """
연구 배경과 방법론을 읽고 연구 내용을 명확하고 구조화된 마크다운 형식으로 요약하세요. 다음 지침을 따르세요:

1. 중요한 과학적 근거와 연구 필요성을 유지하면서 연구 배경을 핵심 포인트만으로 간결하게 요약하세요.
2. 가능한 한 표를 사용하여 방법론을 명확하고 시각적으로 정리하세요.
3. 각 섹션에 적절한 제목과 부제목을 사용하여 계층 구조를 만드세요.
4. 전문 용어를 유지하되, 필요한 경우 간단한 설명을 추가하세요.
5. 전체 요약은 원문 길이의 30%를 초과하지 않아야 합니다.
6. 마지막에 연구의 임상적 의의를 1-2문장으로 강조하세요.

중요: 입력 언어와 관계없이 반드시 한글로만 응답하세요.

템플릿은 다음과 같습니다:

## 1. 연구 배경
## 2. 연구 방법론
### 데이터 선정 및 처리
### 비교 대상 및 평가 방법
### 평가 과정
## 3. 임상적 의의

전문가가 핵심 정보를 빠르게 파악할 수 있도록 간결하고 정보가 풍부한 요약을 한글로 작성하세요.
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
