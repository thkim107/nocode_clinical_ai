"""Per-user research session state, persisted as one JSON file.

Each ``user_code`` owns a flat key/value dict holding everything the
planner, PubMed search and document generation steps produce. The file is
re-read before every access so multiple workers see each other's writes,
and written atomically (tmp + rename) so a crash never leaves it truncated.
"""

import json
import logging
import os
import threading
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class SessionStore:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._users: Dict[str, Dict[str, Any]] = {}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._users = json.load(f)
        except Exception as e:
            logger.error("session store load failed (%s): %s", self._path, e)

    def _save(self) -> None:
        tmp = f"{self._path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._users, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception as e:
            logger.error("session store save failed (%s): %s", self._path, e)

    # -- public API --------------------------------------------------------
    def has_user(self, code: str) -> bool:
        with self._lock:
            self._load()
            return code in self._users

    def get_user_data(self, code: str, key: str, default: Any = None) -> Any:
        with self._lock:
            self._load()
            return self._users.get(code, {}).get(key, default)

    def get_all_user_data(self, code: str) -> Dict[str, Any]:
        with self._lock:
            self._load()
            return dict(self._users.get(code, {}))

    def set_user_data(self, code: str, key: str, value: Any) -> None:
        with self._lock:
            self._load()
            self._users.setdefault(code, {})[key] = value
            self._save()

    def delete_user(self, code: str) -> bool:
        with self._lock:
            self._load()
            if code not in self._users:
                return False
            del self._users[code]
            self._save()
            return True

    def get_all_users(self) -> List[str]:
        with self._lock:
            self._load()
            return list(self._users)


session_store = SessionStore(
    os.path.join(os.environ.get("STATE_DIR", "/app/state"), "users.json")
)
