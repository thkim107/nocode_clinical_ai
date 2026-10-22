# CARIS: Clinical Agentic Research Intelligence System

This repository provides source code for CARIS, the system described in the accompanying manuscript:

**Agentic AI Framework for Hypothesis-to-Report Clinical Research via Indirect and Secure Data Access**

CARIS is a human-in-the-loop agentic AI framework that supports clinical research through natural-language interaction. It connects large language models to task-specific tools through the Model Context Protocol (MCP) and supports research planning, PubMed literature review, cohort construction, IRB document drafting, exploratory data analysis, machine learning model development and evaluation, and clinical research report generation.

The current implementation focuses on structured tabular datasets and predictive modeling. Researchers review and refine generated materials throughout the workflow.

## Research workflow

1. **Research planning:** refine a research question, search PubMed, and define the cohort, outcomes, and candidate variables.
2. **IRB documentation:** draft and revise research-plan and IRB document sections with researcher input.
3. **Interactive machine learning:** perform exploratory analysis, prepare data, develop and evaluate predictive models, and inspect model explanations.
4. **Report generation:** draft a Word research report using TRIPOD+AI-based reporting guidance, with tables and figures from the analysis.

CARIS provides a natural-language interface for these research workflows. Deployment requires administrative configuration of the application, MCP services, database connections, and LLM-provider credentials.

## Implementation and tool provenance

CARIS provides a catalog of 48 LLM-callable tools through four Model Context Protocol (MCP) servers. Twenty-four tools were developed in this work, covering file I/O, predictive modeling, clinical database access, and retrieval of the TRIPOD+AI reporting guideline. The remaining 24 tools support Word document operations and were adapted from the open-source [Office-Word-MCP-Server](https://github.com/GongRzhe/Office-Word-MCP-Server), distributed under the MIT License.

Numerical computation, predictive modeling, and model interpretation rely on established open-source libraries, including scikit-learn, XGBoost, LightGBM, CatBoost, and SHAP. The research-planning and literature-search workflows, the agent orchestration loop, audit logging, and telemetry were developed in-house for CARIS.

The 48 tools constitute the complete registered catalog; the tools made available in an individual request depend on the enabled servers and tool selections. The TRIPOD+AI retrieval tool is hosted by the Word document server. Application-layer workflows and telemetry are separate from this MCP tool count. Upstream attribution and the Word component's license notice are provided in [Third-party notices](THIRD_PARTY_NOTICES.md).

## Repository structure

- [`platform/`](platform/): React/Vite frontend, FastAPI backend, research-planning and literature-search workflows, MCP agent loop, file endpoints, and telemetry APIs.
- [`mcp-servers/file-system/`](mcp-servers/file-system/): file reading, searching, and writing.
- [`mcp-servers/ml-system/`](mcp-servers/ml-system/): data analysis, predictive modeling, visualization, and model interpretation.
- [`mcp-servers/db-connector/`](mcp-servers/db-connector/): clinical database registration, schema information, queries, exports, and research guides.
- [`mcp-servers/docx-system/`](mcp-servers/docx-system/): Word document operations and TRIPOD+AI reporting guidance.
- [`mcp-servers/router/`](mcp-servers/router/): reverse proxy for the four MCP services.
- [`shared/`](shared/): shared audit-logging support and database initialization SQL.

## Deployment and configuration

Start with the [platform setup and architecture guide](platform/README.md). It describes the application services, required environment files, external Docker network, LLM routing, and current setup limitations. The root Compose configuration references a migration file that is absent from this source snapshot; that dependency must be reconciled before the Compose startup path can be considered complete.

The research backend and MCP Workspace chat have separate LLM configurations. In the current implementation, MCP Workspace chat uses OpenRouter. Configuring another provider for the research backend does not change the Workspace chat provider. Database and LLM services must be configured separately; their datasets, credentials, and model weights are not bundled with this repository.

See [Data access and deployment boundaries](DATA_ACCESS.md) for database permissions, tool-output handling, access control, saved research state, and telemetry.

## Data access and availability

CARIS mediates access to configured databases and analysis services through MCP tools. In the intended institutional deployment, databases and analysis files are hosted within the institution's managed environment. Information returned to users and language-model providers depends on the enabled tools and their outputs. Database permissions, permitted queries, output disclosure rules, and LLM-provider settings must be configured for each deployment.

The study evaluated CARIS using MIMIC-IV, INSPIRE, and SyntheticMass. These datasets must be obtained separately from their respective providers under the applicable access conditions. This repository includes software, prompt templates, database adapters, and schema metadata. The study datasets, extracted analysis cohorts, trained study models, and a complete set of per-run experimental outputs are not included in this source release.

Dataset-provider resources referenced by the manuscript are [MIMIC-IV](https://physionet.org/content/mimiciv/3.1/), [INSPIRE](https://physionet.org/content/inspire/1.3/), and [SyntheticMass](https://synthea.mitre.org/downloads). SyntheticMass is synthetic data. The manuscript-specific preparation and schema mapping must be established when reproducing its experiments; the generic Synthea adapter alone does not document that preparation.

## Results reported in the accompanying manuscript

The manuscript reports three independent end-to-end runs for each of three prediction tasks, using Claude Sonnet 4.6 through an API. The following values summarize manuscript Tables 1 and 2:

- **MIMIC-IV — ICU readmission:** 83,101 reported instances; XGBoost selected across the three runs; reported AUROC range 0.684–0.702.
- **INSPIRE — postoperative acute kidney injury:** 100,474 reported instances; CatBoost selected across the three runs; reported AUROC range 0.828–0.891.
- **SyntheticMass — progression from prediabetes to diabetes:** 2,556 reported instances; XGBoost selected across the three runs; reported AUROC range 0.798–0.814.

The manuscript labels these counts as “Number of instances”; it does not identify them as unique-patient or test-set counts. These are study-reported results. The relationship between this public source snapshot and the exact experimental version remains to be documented before attributing an exact reproduction to this release.

The manuscript also evaluates IRB documents and final reports with defined checklists. The [reproducibility guide](REPRODUCIBILITY.md) describes those metrics, evaluator sampling, experiment-specific materials, and implementation details that need study-version alignment.

## Reproducibility

Reproducing the reported experiments requires the corresponding dataset versions, database preparation, cohort definitions, feature and outcome specifications, data-splitting settings, model-search configuration, LLM configuration, and run records. These experiment-specific materials are not all packaged in this source release.

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for the available materials, study protocol, required run information, and differences between the current implementation and the manuscript descriptions.

## Human oversight and scope

CARIS currently supports structured tabular-data and predictive-modeling workflows. Generated research plans, cohort queries, IRB documents, and final reports require expert review. The manuscript's checklist evaluations measure document completeness and coverage under a defined protocol; they do not establish the correctness of every generated statement or the clinical validity of a prediction model.

Researchers and their institutions remain responsible for dataset access, institutional review requirements, appropriate study design, and interpretation of generated outputs. Model calibration, subgroup performance, prediction-time definitions, and the consistency of generated text, tables, and figures require study-specific assessment.

## Citation

Please cite the accompanying manuscript when referring to the CARIS research framework:

> *Agentic AI Framework for Hypothesis-to-Report Clinical Research via Indirect and Secure Data Access*. Accompanying manuscript.

A public manuscript URL, publication details, and formal citation metadata will be added once confirmed by the authors.

## Acknowledgements and third-party licenses

The Word document service includes adaptations of Office-Word-MCP-Server. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for upstream attribution and the applicable MIT License notice. Numerical and machine-learning dependencies retain their respective licenses.

A project-wide license for the CARIS-authored code has not been specified in this source release. The upstream component's MIT License applies to that component; it does not select a license for the entire repository.
