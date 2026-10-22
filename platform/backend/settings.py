"""Central place for environment configuration.

Import this module first (main.py does) so ``.env`` is loaded before any
module reads ``os.environ`` at import time (research.prompts, llm_manager).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Shared volume browsed by the file manager and written by MCP servers
    data_dir: Path = Path(os.getenv("DATA_DIR", "/app/data"))
    # Platform-private state (research session store). Must NOT be inside data_dir.
    state_dir: Path = Path(os.getenv("STATE_DIR", "/app/state"))

    prompt_lang: str = os.getenv("PROMPT_LANG", "en").strip().lower()

    mcp_router_url: str = os.getenv("MCP_ROUTER_URL", "http://router:8000")
    audit_db_url: str = os.getenv("AUDIT_DB_URL", "")


settings = Settings()
if settings.prompt_lang not in ("ko", "en"):
    raise RuntimeError(f"PROMPT_LANG must be 'ko' or 'en', got {settings.prompt_lang!r}")
os.environ["PROMPT_LANG"] = settings.prompt_lang
settings.state_dir.mkdir(parents=True, exist_ok=True)
