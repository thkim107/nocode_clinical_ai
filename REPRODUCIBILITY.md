# Reproducibility and study provenance

This repository accompanies **“Agentic AI Framework for Hypothesis-to-Report Clinical Research via Indirect and Secure Data Access”** and provides the CARIS (Clinical Agentic Research Intelligence System) implementation. This document records the study-reported configuration, the materials available in the repository, and the information needed to reproduce the experiments.

The source snapshot reviewed for this document is commit [`30c4a6bed905d11bc5a755ad867f85730cbd1416`](https://github.com/thkim107/nocode_clinical_ai/tree/30c4a6bed905d11bc5a755ad867f85730cbd1416). This identifies the published source snapshot. Whether it is the exact version used for the manuscript experiments requires author confirmation. Results below are transcribed from the manuscript; they have not been independently regenerated from this repository.

## Study-reported configuration

The manuscript reports **three independent end-to-end experiments for each of three clinical prediction tasks, for nine experiments in total**. All experiments used **Claude Sonnet 4.6 through an API** and were conducted by one author with clinical AI research expertise. The manuscript reports that no GPUs were used in its experimental setup; it does not describe the hardware of the remote LLM service. Human interaction was part of the workflow: users refined research plans and IRB documents and reviewed proposed analyses and tool executions. The three runs should therefore be interpreted as repeated supervised workflows, rather than three operators or a fully unattended benchmark. (Manuscript, pp. 4–6.)

The manuscript describes training-set grid search with stratified five-fold cross-validation, with preprocessing refitted within each training fold and a held-out test set excluded from preprocessing and hyperparameter tuning. It describes removal of columns with more than 50% missing values, mean/mode imputation, categorical encoding, and optional feature selection. It also describes AUROC confidence intervals, DeLong comparisons, and bootstrap resampling with 2,000 resamples. The implementation differences listed below must be reconciled when identifying the experiment version. (Manuscript, p. 3; Supplementary Note 7.)

## Datasets, tasks, and reported results

The counts below use the label **“Number of instances”** from manuscript Table 1. They should not be interpreted as counts of unique patients without the corresponding cohort specification. AUROC ranges cover the three experiments in manuscript Table 2.

- **MIMIC-IV: ICU readmission.** The manuscript describes Beth Israel Deaconess Medical Center data from 2008–2022 and includes adults who survived ICU and hospital discharge. The outcome is ICU readmission between 48 hours and 30 days after discharge. It reports **83,101 instances**, with XGBoost selected in all three experiments and AUROCs of **0.684, 0.684, and 0.702**. The manuscript's data-availability section links to [MIMIC-IV 3.1](https://physionet.org/content/mimiciv/3.1/).
- **INSPIRE: postoperative acute kidney injury.** The manuscript describes Seoul National University Hospital perioperative data from 2011–2020, with AKI defined using KDIGO serum-creatinine criteria and cardiothoracic surgery and cardiovascular procedures excluded. It reports **100,474 instances**, with CatBoost selected in all three experiments and AUROCs of **0.891, 0.828, and 0.887**. The data-availability section links to [INSPIRE 1.3](https://physionet.org/content/inspire/1.3/).
- **SyntheticMass: prediabetes-to-diabetes progression.** The manuscript describes synthetic Massachusetts longitudinal patient data generated using Synthea and represented in OMOP-CDM. It includes adults aged 18–75 with prediabetes and no prior diabetes. Prediabetes is defined by fasting glucose 100–125 mg/dL, HbA1c 5.7–6.4%, or two-hour OGTT 140–199 mg/dL; incident diabetes uses thresholds of fasting glucose at least 126 mg/dL, HbA1c at least 6.5%, or two-hour OGTT at least 200 mg/dL. It reports **2,556 instances**, with XGBoost selected in all three experiments and AUROCs of **0.798, 0.814, and 0.807**. The data-availability section links to the [Synthea downloads page](https://synthea.mitre.org/downloads).

These descriptions summarize the manuscript, pp. 4 and 7 and Tables 1–2. Exact cohort SQL, index times, follow-up rules, predictor availability windows, exclusion order, and patient-level grouping are still necessary for reproduction. Obtain source datasets under their providers' applicable access conditions; the repository does not distribute them.

## Evaluation of generated documents

IRB documents were assessed with **25 checklist items** covering content completeness, non-expert accessibility, ethical adequacy, and cross-section consistency. Reported overall pass rates were **93.3% for Claude Sonnet 4.6, 90.7% for GPT-5.6 Sol, and 81.8% for human evaluators**. Final reports were assessed with **28 TRIPOD+AI-based checklist items**, with reported coverage of **90.5%, 84.5%, and 89.3%**, respectively. These are document checklist results, not measures of predictive accuracy or clinical validation. (Manuscript, pp. 5–6; Supplementary Notes 11–12 and Tables S2–S3.)

The evaluation sampling differs between LLMs and humans. Each LLM evaluator assessed the three runs for each task. For human evaluation, **one run was randomly selected per task and independently assessed by three clinical research evaluators**, who were blinded to the LLM results and one another's assessments. Thus, the design yields 225 item judgments per evaluator type for IRB documents (25 × 3 tasks × 3 runs or raters), and 252 for final reports (28 × 3 × 3). For humans, these judgments concern three selected documents of each type, each reviewed by three raters; they do not represent nine separately selected documents. The reported final-report agreement analysis uses majority-vote judgments across **84 item–task pairs** (28 × 3). (Manuscript, pp. 5–6.)

The manuscript also reports institutional exemption review of one selected IRB document per task, with minor revisions followed by approval. Those determinations concern the submitted studies; each deployment needs its own applicable data-access and institutional review arrangements. (Manuscript, pp. 5–6.)

## Materials available in this repository

The repository includes frontend and backend source, MCP services, deployment configuration, environment examples, bilingual research-planning/PubMed/IRB prompts, dataset schema descriptions, concept-mapping metadata, generic cohort and analysis guides, and a TRIPOD+AI report-writing prompt. Relevant locations include:

- [`platform/backend/research/prompts/`](platform/backend/research/prompts/)
- [`mcp-servers/db-connector/documents/`](mcp-servers/db-connector/documents/)
- [`mcp-servers/docx-system/documents/tripod_ai_system_prompt.txt`](mcp-servers/docx-system/documents/tripod_ai_system_prompt.txt)
- [`mcp-servers/ml-system/`](mcp-servers/ml-system/) and [`shared/`](shared/)

The release does not include the clinical databases, access credentials, experiment-specific cohort SQL, extracted analysis datasets, fitted models, test predictions, split assignments, complete run manifests, or machine-readable evaluator-rating files. Generated study documents are described in the accompanying supplementary materials; the manuscript and supplementary PDFs are not bundled here. Schema descriptions and synthetic-data metadata do not substitute for the study's loaded databases or conversion procedures.

## Differences requiring study-version reconciliation

The following observations describe the available source and its relationship to the manuscript. They do not establish which implementation produced the reported experiments.

1. **Feature selection and the final split.** In [`modeling.py`](mcp-servers/ml-system/modeling.py), `train_model` evaluates feature combinations by cross-validation on the loaded dataset, ranks the combinations, and then creates the train/test split for fitting the selected combinations. Consequently, the earlier feature-combination ranking uses data from which the later test subset is drawn. The experiment's actual split and selection order must be documented before treating this routine as the manuscript's held-out evaluation protocol. The same file explicitly states that the RFE, Boruta-SHAP, SelectKBest-MI, and random-forest selection functions were removed; the corresponding `run_feature_selection` registration is commented out in [`main.py`](mcp-servers/ml-system/main.py). Those manuscript-described selectors should not be assumed available in this snapshot.
2. **Confidence intervals and statistical comparisons.** The combination-analysis routine in `modeling.py` computes percentile bounds across cross-validation fold scores. A separate ROC visualization routine in [`analytics.py`](mcp-servers/ml-system/analytics.py) specifies **200 bootstrap resamples**. Neither establishes the manuscript's described 2,000-resample procedure, and a DeLong implementation was not identified in the reviewed source. Reproduction requires the actual statistical code, prediction inputs, resampling unit, random seed, and comparison specification used in the study.
3. **Frontend implementation.** Supplementary Note 9 describes NiceGUI. The published [`platform/frontend/package.json`](platform/frontend/package.json) instead specifies React, TypeScript, and Vite. The relationship between these interface versions and the experimental workflow needs to be recorded.
4. **SyntheticMass database representation.** The manuscript describes OMOP-CDM. The current [database registry](mcp-servers/db-connector/config/databases.yaml) has a `synthea` entry for a Synthea database and a separate `cdm` entry described as HIRA OMOP-CDM. Neither entry alone identifies the study's SyntheticMass OMOP database. Reproduction requires its release, loading or conversion process, vocabulary versions, schema, and task-specific mappings.
5. **Provenance of supplementary generated reports.** Supplementary Notes 13–15 contain generated report drafts whose dataset versions or performance values differ from the manuscript's main results. For example, the MIMIC draft describes v2.2, whereas the manuscript data-availability link points to v3.1. Each example should be mapped to its run and source version before being used as a reproduction target. The manuscript's main results are the values summarized above.

## Run manifest needed for reproduction

For each of the nine experiments, retain a manifest and its associated artifacts with the following information:

- **Identity and environment:** run identifier, exact source commit, execution date, OS/runtime and dependency versions, container image identifiers, CPU/memory allocation, and relevant configuration.
- **LLM and interaction settings:** provider, exact model identifier, API parameters, prompt versions, enabled tools, initial hypothesis, user revisions and approvals, and complete tool-execution records with protected content handled under the applicable access rules.
- **Data and cohort:** dataset release and checksums where permitted, schema and vocabulary versions, loading/conversion procedure, executed SQL, outcome and predictor definitions, prediction time, exclusions, missingness rules, and counts at each cohort step.
- **Model development:** patient or encounter grouping, saved split assignments, random seeds, feature-selection order, feature lists, preprocessing, imbalance handling, algorithms, hyperparameter grids, cross-validation configuration, selection criterion, and fitted model artifacts.
- **Performance and reporting:** true labels and predicted probabilities in a controlled location, decision thresholds, positive-class definition, precision/recall/F1 averaging convention, AUROC calculation, confidence-interval method, resampling unit/count/seed, statistical comparisons, and the exact generated documents and figures.
- **Document evaluation:** checklist version, evaluator model settings, selected human-review runs, selection procedure, per-item judgments, revision history, aggregation rules, and majority-vote/coverage calculations.

## Author confirmation and interpretation

Exact reproduction requires author confirmation of the experimental source revision, per-run data releases and schemas, validation and statistical procedures, and the connection between supplementary examples and the nine reported runs. These items should be resolved through a versioned study manifest and appropriate supporting artifacts. The source snapshot alone does not establish them.

Successful deployment demonstrates that the software can run in a configured environment; reproducing the paper additionally requires matching the study inputs, decisions, and evaluation records. Human review remains necessary for cohort definitions, feature timing, analyses, IRB documentation, and generated conclusions. Database queries and file previews can return record-level values, so an external LLM deployment also requires an explicit policy for what tool outputs may be sent to the provider.

## Evidence references

Study statements above refer to the author-supplied manuscript **“Agentic AI Framework for Hypothesis-to-Report Clinical Research via Indirect and Secure Data Access”** (11-page version), especially pp. 3–7 and Tables 1–2 on p. 10, and its **Supplementary Materials** (180-page version): Notes 7 and 9, Notes 11–12 with Tables S2–S3, and generated report examples in Notes 13–15. Page numbers refer to these supplied PDF versions. No publication date, DOI, or experiment commit is inferred from the repository upload date.
