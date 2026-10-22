# platform

Research AI Platform: one container serving the React UI and the API.

```
platform/
├── Dockerfile                 node build stage (frontend) + python runtime
├── backend/
│   ├── main.py                app assembly only
│   ├── settings.py            environment configuration (loaded first)
│   ├── files/                 /api/ls, preview, upload … over /app/data (volume_storage)
│   ├── chat/                  /api/chat/*   LLM chat with MCP tools via the router
│   └── research/              /api/research/*
│       ├── routers/           planner, pubmed, llm (config), session (snapshot)
│       ├── llm_manager.py     provider abstraction (openai / anthropic / openrouter / snuhllm)
│       ├── pubmed_manager.py  NCBI E-utilities client
│       ├── session_store.py   per-user state, JSON file under /app/state
│       └── prompts/ko, en     selected by PROMPT_LANG
└── frontend/                  React + Vite (tabs: Planner, PubMed, IRB Documentation, MCP Workspace)
```

## Run

```bash
cp platform/backend/.env.example platform/backend/.env   # fill in keys
docker compose build platform && docker compose up -d platform
```

The app listens on host port 8003. `AUDIT_DB_URL` is injected by compose.

## Development

Backend: `cd platform/backend && uvicorn main:app --reload` (needs `STATE_DIR` and `DATA_DIR` pointing at writable local dirs).
Frontend: `cd platform/frontend && npm install && npm run dev` — Vite proxies `/api` to `localhost:8000`.

## State

| Path         | Contents                                   | Mount                          |
|--------------|--------------------------------------------|--------------------------------|
| `/app/data`  | shared research files (also written by MCP servers) | `./mcp-servers/volume_storage` |
| `/app/state` | `users.json` session store                  | named volume `platform_state`  |
