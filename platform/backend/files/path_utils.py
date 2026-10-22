from pathlib import Path

BASE_DIR = Path("/app/data")


def resolve_safe_path(user_path: str) -> Path:
    if not user_path or user_path in (".", "/", ""):
        return BASE_DIR.resolve()
    user_path = user_path.lstrip("/")
    resolved = (BASE_DIR / user_path).resolve()
    base_resolved = BASE_DIR.resolve()
    if not str(resolved).startswith(str(base_resolved)):
        raise ValueError("Access denied: path escapes base directory")
    return resolved


def sanitize_filename(name: str) -> str:
    name = Path(name).name
    forbidden = set('<>:"|?*\x00')
    sanitized = "".join(c for c in name if c not in forbidden)
    if not sanitized or sanitized.startswith("."):
        raise ValueError(f"Invalid filename: {name}")
    return sanitized
