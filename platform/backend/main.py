"""Research AI Platform - single FastAPI application.

Routers:
  /api/ls, /api/preview, ...   files.router      shared volume browser
  /api/chat/*                  chat.router       LLM chat with MCP tools
  /api/research/*              research.routers  planner, PubMed, document generation, LLM config
  /api/telemetry/*             telemetry_router  protected metrics and CSV exports
  /                            built React SPA (platform/frontend)
"""

import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from settings import settings  # noqa: F401  (loads .env and validates before other imports)
from telemetry import TelemetryMiddleware
from telemetry_router import router as telemetry_router
from files.router import router as files_router
from chat.router import router as chat_router
from research.routers.planner import research_plan_router
from research.routers.pubmed import pubmed_search_router
from research.routers.llm import llm_router
from research.routers.session import session_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Research AI Platform")
app.add_middleware(TelemetryMiddleware)
app.include_router(files_router)
app.include_router(chat_router)
app.include_router(telemetry_router)

research_router = APIRouter(prefix="/api/research")
for r in (research_plan_router, pubmed_search_router, llm_router, session_router):
    research_router.include_router(r)
app.include_router(research_router)

# Serve the built frontend - must be mounted last.
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

logger.info("platform started")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
