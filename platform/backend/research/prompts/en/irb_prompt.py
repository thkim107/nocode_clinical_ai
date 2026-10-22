TOPIC_INFERENCE_PT = """
You are tasked with refining the user's research topic into a form suitable for an IRB application.

[Task Objectives]
1. Extract core research topic: When the user provides a lengthy explanation or lists multiple elements, identify and clearly summarize the most essential research topic.
2. Convert to noun phrase form: Remove predicates (e.g., 'to analyze', 'aiming to study') and express the research topic as a concise noun phrase.
3. Translate to English: Translate the refined topic into English.

[Refinement Criteria]
- Exclude supplementary explanations, background, and methodological details; include only the core subject and objective of the research
- Maintain appropriate length and clarity for use as an IRB application title (typically 10-20 words)
- Preserve appropriate technical terminology from the medical and AI domains

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{"modified_sentence": "Refined research topic (noun phrase form)", "translated_sentence": "Research topic translated into English"}
```
"""


TOPIC_PT = """
You need to further specify the user's research. The purpose is for writing an IRB (Institutional Review Board) application, and you should create questions based on the following example.
{"ExampleQuery": "Are there any papers that use a Vision model to convert images into embedding vectors, build a database, and then retrieve a few images closest to a specific image's embedding vector to classify or find characteristics of that image? Or can you find and organize papers with similar topics? In terms of language domain, it's similar to a RAG system.",
"ExampleResponse": "I'd like to confirm the following for the paper search: - Do you have a preference for specific Vision models (e.g., CLIP, DINO, ViT, etc.)? - Do you want to find research applied in a specific domain (e.g., medical, autonomous driving, product search, etc.)? - Do you want recent research? Is there a specific year range? - Do you want to find papers from specific academic databases (e.g., arXiv, IEEE, CVPR, ECCV, NeurIPS, etc.)?
With this information, I can provide a more accurate list of papers!"}

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{"subquery_1": "subquery_1", "subquery_2": "subquery_2"}
```
"""

RESEARCH_PURPOSE_PT = """
Write the research purpose based on the following user prompt. The user prompt is for writing an IRB (Institutional Review Board) application.

[Unique Role of the Research Purpose Section]
This section focuses on "WHY" this research is being conducted:
- Background and necessity of the research (limitations of existing studies, problems to be solved)
- Core research questions or hypotheses
- Academic goals to be achieved through the research

[Content NOT to Cover in This Section]
- Specific research methods or procedures (covered in Research Method section)
- Research type or design structure (covered in Research Design section)
- Statistical analysis or validation methods (covered in Validity Evaluation section)

Maintain an academic and professional tone and compose 3-4 lines in one paragraph.

IMPORTANT:
- You must respond in English only, regardless of the input language.
- If "Previously Generated Sections" is provided, DO NOT repeat any content from those sections. Use different expressions, vocabulary, and focus on unique aspects.

Respond in the following JSON format:
```json
{"research_purpose": "research purpose in English"}
```
"""

RESEARCH_DESIGN_PT = """
Write the research design based on the following user prompt. The user prompt is for writing an IRB (Institutional Review Board) application.

[Unique Role of the Research Design Section]
This section focuses on the "STRUCTURAL FRAMEWORK" of the research:
- Research type (retrospective/prospective, cross-sectional/longitudinal, observational/experimental, etc.)
- Research design approach (cohort, case-control, randomized, single-arm, etc.)
- Overview of research subjects and study period
- Whether comparison groups are established and their structure

[Content NOT to Cover in This Section]
- Background or necessity of the research (covered in Research Purpose section)
- Specific data collection/measurement procedures (covered in Research Method section)
- Statistical analysis methods (covered in Validity Evaluation section)
- Expected effects or outcomes (covered in Expected Effects/Anticipated Results sections)

Maintain an academic and professional tone and compose 3-4 lines in one paragraph.

IMPORTANT:
- You must respond in English only, regardless of the input language.
- If "Previously Generated Sections" is provided, DO NOT repeat any content from those sections. Use different expressions, vocabulary, and focus on unique aspects not covered in previous sections.

Respond in the following JSON format:
```json
{"research_design": "research design in English"}
```
"""

RESEARCH_METHOD_PT = """
Write the research method based on the following user prompt. The user prompt is for writing an IRB (Institutional Review Board) application.

[Unique Role of the Research Method Section]
This section focuses on "HOW" the research is conducted with specific procedures:
- Subject selection criteria (inclusion/exclusion criteria)
- Data collection methods and procedures (EMR extraction, surveys, tests, etc.)
- Definition and measurement methods of key variables
- Data processing and anonymization procedures

[Content NOT to Cover in This Section]
- Background or objectives of the research (covered in Research Purpose section)
- Research type or design structure (covered in Research Design section)
- Statistical significance validation methods (covered in Validity Evaluation section)
- Expected effects or significance of the research (covered in Expected Effects section)

Maintain an academic and professional tone and compose 3-4 lines in one paragraph.

IMPORTANT:
- You must respond in English only, regardless of the input language.
- If "Previously Generated Sections" is provided, DO NOT repeat any content from those sections. Use different expressions, vocabulary, and focus on unique aspects not covered in previous sections.

Respond in the following JSON format:
```json
{"research_method": "research method in English"}
```
"""

VALIDITY_EVALUATION_PT = """
Write the validity evaluation method for the research based on the following user prompt. The user prompt is for writing an IRB (Institutional Review Board) application.

[Unique Role of the Validity Evaluation Section]
This section focuses on "VALIDATION AND ANALYSIS METHODS" of research results:
- Statistical analysis methods to be used (t-test, ANOVA, regression analysis, survival analysis, etc.)
- Statistical significance level and power settings
- Model performance evaluation metrics (for AI research: AUC, accuracy, sensitivity, specificity, etc.)
- Confounding variable adjustment methods and sensitivity analysis

[Content NOT to Cover in This Section]
- Background or objectives of the research (covered in Research Purpose section)
- Research design type (covered in Research Design section)
- Data collection procedures (covered in Research Method section)
- Social/academic impact of the research (covered in Expected Effects section)

Maintain an academic and professional tone and compose 3-4 lines in one paragraph.

IMPORTANT:
- You must respond in English only, regardless of the input language.
- If "Previously Generated Sections" is provided, DO NOT repeat any content from those sections. Use different expressions, vocabulary, and focus on unique aspects not covered in previous sections.

Respond in the following JSON format:
```json
{"validity_evaluation": "evaluation method in English"}
```
"""

EXPECTED_EFFECTS_PT = """
Write the expected effects based on the following user prompt. The user prompt is for writing an IRB (Institutional Review Board) application.

[Unique Role of the Expected Effects Section]
This section focuses on the "IMPACT AND SIGNIFICANCE" of the research:
- Academic contributions (differentiation from existing research, creation of new knowledge)
- Clinical significance (applicability in clinical practice)
- Social/policy contributions (healthcare system improvement, guideline development, etc.)
- Foundation for follow-up research

[Content NOT to Cover in This Section]
- Background or necessity of the research (covered in Research Purpose section)
- Methodological details of the research (covered in Research Method/Validity Evaluation sections)
- Specific numerical predictions or data patterns (covered in Anticipated Results section)

Avoid overly optimistic expressions and include objective predictions.
Maintain an academic and professional tone and compose 3-4 lines in one paragraph.

IMPORTANT:
- You must respond in English only, regardless of the input language.
- If "Previously Generated Sections" is provided, DO NOT repeat any content from those sections. Use different expressions, vocabulary, and focus on unique aspects not covered in previous sections.

Respond in the following JSON format:
```json
{"expected_effects": "expected effects in English"}
```
"""

ANTICIPATED_RESULTS_PT = """
Write the anticipated results based on the following user prompt. The user prompt is for writing an IRB (Institutional Review Board) application.

[Unique Role of the Anticipated Results Section]
This section focuses on "SPECIFIC EXPECTED OUTCOMES" of the research:
- Expected data patterns and trends (e.g., correlations between specific variables, differences between groups)
- Expected direction when testing hypotheses
- Expected level of model performance (for AI research)
- Expected results for primary/secondary outcome variables

[Content NOT to Cover in This Section]
- Background or necessity of the research (covered in Research Purpose section)
- Research design or methodology (covered in Research Design/Research Method sections)
- Academic/clinical significance or impact (covered in Expected Effects section)
- Explanation of statistical analysis methods (covered in Validity Evaluation section)

Maintain an academic and professional tone and compose 3-4 lines in one paragraph.

IMPORTANT:
- You must respond in English only, regardless of the input language.
- If "Previously Generated Sections" is provided, DO NOT repeat any content from those sections. Use different expressions, vocabulary, and focus on unique aspects not covered in previous sections.

Respond in the following JSON format:
```json
{"anticipated_results": "anticipated results in English"}
```
"""

ITEM_REVISION_PT = """
Revise the existing paragraph according to the user's request. This paragraph is for writing an IRB (Institutional Review Board) application. The existing response is given in Key:Value format. The Key is the category of the text and is one of ['research_purpose', 'research_design', 'research_method', 'validity_evaluation', 'expected_effects', 'anticipated_results']. The Value is the pre-written text. Maintain most of the content while reflecting the requirements, and compose 3-4 lines in one paragraph with an academic and professional tone.

IMPORTANT: You must respond in English only, regardless of the input language.

Respond in the following JSON format:
```json
{"revised_answer": "revised answer in English"}
```
"""

pt_order_list = {
    'research_purpose': RESEARCH_PURPOSE_PT,
    'research_design': RESEARCH_DESIGN_PT,
    'research_method': RESEARCH_METHOD_PT,
    'validity_evaluation': VALIDITY_EVALUATION_PT,
    'expected_effects': EXPECTED_EFFECTS_PT,
    'anticipated_results': ANTICIPATED_RESULTS_PT
}

# Korean aliases for backward compatibility
주제추론_PT = TOPIC_INFERENCE_PT
주제_PT = TOPIC_PT
연구목적_PT = RESEARCH_PURPOSE_PT
연구설계_PT = RESEARCH_DESIGN_PT
연구방법_PT = RESEARCH_METHOD_PT
유효성평가_PT = VALIDITY_EVALUATION_PT
기대효과_PT = EXPECTED_EFFECTS_PT
예상결과_PT = ANTICIPATED_RESULTS_PT
문항수정_PT = ITEM_REVISION_PT
