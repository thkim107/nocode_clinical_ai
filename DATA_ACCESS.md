# Data access and handling

This document describes the data flow and access controls in the current public source. The datasets, permissions, and software version used for the manuscript experiments must be documented separately in [REPRODUCIBILITY.md](REPRODUCIBILITY.md).

## Obtaining and connecting data

The repository contains application code, database schema descriptions, and terminology reference information. It does not distribute the patient-level study datasets, trained study models, or a complete set of experiment outputs. Obtain each dataset separately from its provider and follow its access requirements and the requirements of the institution conducting the research.

The [database registry](mcp-servers/db-connector/config/databases.yaml) defines connection configurations for CDM, KMIMIC, MIMIC-IV, INSPIRE, and Synthea. A configured adapter does not provide access to a dataset. Operators must supply reachable PostgreSQL databases, compatible schemas, and appropriate credentials through the [database connector environment configuration](mcp-servers/db-connector/.env.example). The root Compose stack provisions an audit database; it does not provision or import these clinical databases.

The checked-in [Synthea metadata](mcp-servers/db-connector/documents/synthea/Information.json) describes native Synthea tables such as `patients`, `encounters`, and `conditions`. Reproducing experiments that use an OMOP-CDM representation also requires the corresponding conversion, schema, and cohort definitions.

## Database permissions and query results

Database access depends on the permissions of the configured database account. Use a read-only database account when the intended workflow is read-only. The current [SQL executor](mcp-servers/db-connector/core/query_executor.py) executes submitted SQL and can commit statements that do not return rows; it does not enforce a SELECT-only policy or read-only transactions.

The default query preview returns a limited number of rows. This limits the returned preview, not the database account's permissions, and does not de-identify the returned values. CSV export can retrieve larger result sets. Restrict available tables, fields, and operations through the database configuration and permissions appropriate to the deployment.

## Language-model routing and transmitted content

The [research backend](platform/backend/research/llm_manager.py) supports OpenAI, Anthropic, OpenRouter, and an externally configured OpenAI-compatible endpoint through the SNUHLLM adapter. Its provider and model are configured separately from MCP Workspace chat. The repository does not include model weights or a local model-serving service.

In the current implementation, [MCP Workspace chat](platform/backend/chat/router.py) sends requests to OpenRouter using `OPENROUTER_API_KEY` and `CHAT_MODEL`. Changing the research backend's provider or configuring a local SNUHLLM endpoint does not change the provider used by MCP Workspace chat.

Clinical databases and generated files are hosted in operator-configured services. Tool outputs can contain database row values, file previews, or other research content, and these outputs may be included in subsequent language-model requests. The current implementation does not automatically de-identify tool responses or restrict them to aggregate statistics. Truncation of a result displayed in the interface does not establish that the content sent to the model was similarly truncated.

Choose permitted tool outputs and model providers according to the data being used and the requirements of the deployment. Hosting a database locally does not, by itself, make all model processing local.

## Sessions, shared files, and authentication

`user_code` identifies saved research sessions; it is not an authentication credential. The current research, file, and chat APIs do not provide an integrated login or per-user authorization layer. Deployments that require restricted access must provide that access control externally.

The root Compose configuration mounts a shared research workspace at `/app/data` and stores research sessions separately under `/app/state`. These stores can contain uploaded data, generated files, and user-provided research content. A session identifier does not establish a separate authenticated file workspace.

`TELEMETRY_VIEWER_TOKEN` protects the [telemetry API](platform/backend/telemetry_router.py) only. It does not authenticate access to the rest of the application.

## Telemetry and retention

[Operational telemetry](platform/backend/telemetry.py) records workflow events, timing, usage, and summarized request/response information. The normal telemetry paths summarize payloads using properties such as lengths, counts, and hashes instead of storing complete prompts and tool responses. This is separate from the research session store, which saves research content. Error messages and operator-supplied metadata also need review before logs are shared.

Configure a deployment-specific `TELEMETRY_HMAC_KEY` for pseudonymized session identifiers; the Compose fallback is a development value. Configure access, retention, backup, and deletion for research files, session state, and the audit database separately. Stopping the containers does not remove their persistent stores. See the [platform documentation](platform/README.md) for configuration and storage locations.
