"""
Path Validator - Security validation for file paths.
"""

from pathlib import Path


def check_inside(candidate: str, root: str) -> Path:
    """
    Ensure candidate path is within the allowed root directory.

    Args:
        candidate: Path to validate
        root: Allowed root directory (default: /app/data)

    Returns:
        Resolved Path object

    Raises:
        ValueError: If path is outside allowed root
    """
    root_path = Path(root)
    candidate_path = Path(candidate)
    resolved = candidate_path.expanduser().resolve()

    if not str(resolved).startswith(str(root_path.resolve())):
        raise ValueError(f"Access denied: Path must be under {root}")

    return resolved
