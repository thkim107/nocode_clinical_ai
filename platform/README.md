# CARIS platform

The platform serves the React interface and FastAPI API from one container. The interface includes Planner, PubMed, IRB Documentation, and MCP Workspace. MCP services and the audit database run as separate services in the [root Compose configuration](../docker-compose.yaml).

## Architecture

- [Dockerfile](Dockerfile) builds the frontend with Node.js and packages it with the Python backend. It also copies the shared audit logger through the Compose `shared` build context.
- [backend/main.py](backend/main.py) assembles the API and serves the built frontend.
- [backend/settings.py](backend/settings.py) loads environment configuration before other backend modules.
- [backend/files/](backend/files/) provides shared workspace operations through endpoints such as `/api/ls`, `/api/preview`, and `/api/upload`.
- [backend/chat/](backend/chat/) provides `/api/chat/*` and calls MCP tools through the router service.
- [backend/research/](backend/research/) provides `/api/research/*` for planning, PubMed search, document generation, provider configuration, and saved sessions. Its PubMed manager uses NCBI E-utilities.
- [backend/telemetry_router.py](backend/telemetry_router.py) provides the token-protected `/api/telemetry/*` endpoints.
- [frontend/](frontend/) contains the React and Vite application.

Research prompts are selected from the English or Korean prompt directories using `PROMPT_LANG=en` or `PROMPT_LANG=ko`.

## Deployment status and prerequisites

These instructions describe the intended setup based on source inspection. Deployment has not been validated for this public source snapshot.

**The root Compose workflow currently has a startup blocker:** it mounts `deploy/migrations/001_telemetry.sql`, which is absent from this snapshot. The platform waits for that migration service to complete successfully. Restore the intended migration or review and reconcile the migration configuration before attempting to start the stack. The existing [shared/init_audit_db.sql](../shared/init_audit_db.sql) already contains telemetry schema initialization, so the missing migration must be resolved consistently with that initialization.

The intended deployment also requires:

- Docker Engine and Docker Compose with support for `build.additional_contexts`.
- An existing Docker network named `research-ai`, because the root Compose file marks it as external. If it does not already exist, create it with `docker network create research-ai`.
- Configured language-model credentials or an accessible model endpoint for the research backend; MCP Workspace chat requires OpenRouter credentials.
- Reachable PostgreSQL databases and appropriate account permissions for any clinical database tools that will be used. The stack does not import the study datasets.
- Writable storage for the shared research workspace, session state, and audit database.
- External access control when access to research content or application functions must be restricted. The current application does not provide an integrated login for its research, file, and chat APIs.

The root Compose file publishes the platform on host port `8003`, the MCP router on `8002`, and the database connector on `8005`. Account for all of these published services when configuring access. See [Data access and handling](../DATA_ACCESS.md).

## Configuration

For a new checkout, prepare both environment files from the repository root:

```bash
cp platform/backend/.env.example platform/backend/.env
cp mcp-servers/db-connector/.env.example mcp-servers/db-connector/.env
```

Fill in the required values before starting services. Preserve existing configuration files when updating an installation.

### Language models

The [research LLM manager](backend/research/llm_manager.py) supports `openai`, `anthropic`, `openrouter`, and `snuhllm`. Set `LLM_DEFAULT_PROVIDER` and `LLM_DEFAULT_MODEL` explicitly, together with the selected provider's credentials and endpoint settings. The SNUHLLM adapter connects to an externally provided OpenAI-compatible endpoint; no model server or model weights are bundled. An endpoint using `localhost` inside a container refers to that container, so configure a URL reachable from the platform container.

[MCP Workspace chat](backend/chat/router.py) is configured separately through `OPENROUTER_API_KEY` and `CHAT_MODEL` and currently uses OpenRouter. Selecting a local research provider does not reroute Workspace chat. Tool responses, including database values or file content, may be sent to that provider as part of the conversation; see [Data access and handling](../DATA_ACCESS.md).

### Infrastructure and telemetry

`MCP_ROUTER_URL` defaults to `http://router:8000` for the Compose network. The root Compose file injects `AUDIT_DB_URL`; it also contains development audit-database credentials that should be replaced consistently when preparing a shared deployment.

The root Compose file sets `PROMPT_LANG`, `APP_VERSION`, `PROMPT_VERSION`, and `TELEMETRY_HMAC_KEY` through its `environment` entries using Compose interpolation. Supply these values through the shell or the repository-root `.env` used by Compose; editing only `platform/backend/.env` does not override those entries. Use a deployment-specific HMAC key instead of the development fallback. Record meaningful application and prompt versions when collecting experiment telemetry.

Set `TELEMETRY_VIEWER_TOKEN` in the backend environment to enable protected telemetry access. This token applies only to telemetry endpoints. Normal telemetry calls summarize payloads, while the separate session store retains research content.

## Intended Compose workflow

After resolving the missing migration and completing the configuration and prerequisites above, the intended commands from the repository root are:

```bash
docker compose build
docker compose up -d
```

With a successful startup, the platform is configured to serve the interface and API at `http://localhost:8003`. These commands have not been executed to validate this snapshot.

## Development

The Dockerfile uses Node.js 20 for the frontend build and Python 3.11 for the backend. Frontend development commands are:

```bash
cd platform/frontend
npm install
npm run dev
```

The [Vite configuration](frontend/vite.config.ts) proxies `/api` to `http://localhost:8000`. The root Compose deployment publishes the backend on `8003`, so align the development proxy with the backend being used.

The backend entry point is `main:app` under `platform/backend`. A host-native development environment needs the backend dependencies, reachable MCP and audit services, the shared `audit_logger` module on the Python import path, and writable application directories. The [file path helper](backend/files/path_utils.py) currently fixes the file workspace at `/app/data`; setting `DATA_DIR` alone does not relocate that workspace. Account for these requirements before using `uvicorn main:app --reload`. A complete host-native setup has not been validated for this snapshot.

## Persistent state

- `/app/data` contains shared research files, including files written by MCP services. In root Compose it is a bind mount of `mcp-servers/volume_storage`.
- `/app/state` contains `users.json`, the research session store. Root Compose mounts the named volume `platform_state` there.
- The audit database persists separately in the named volume `audit_db_data`.

`user_code` is a session key, not an authenticated user identity. Configure access and retention for the shared workspace, saved sessions, and audit database separately. Ordinary container shutdown leaves these persistent stores in place.
