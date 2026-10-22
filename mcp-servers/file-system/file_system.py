from typing import Any, List, Dict, Sequence
import json
from datetime import datetime
from pathlib import Path
import difflib
from PIL import Image
import PyPDF2
import csv
import base64
import io
import pandas as pd



def _normalise(p: str | Path) -> Path:  # pathlib already uses British spelling ;-)
    """Return *absolute* `Path` with symlinks resolved and `~` expanded."""
    return Path(p).expanduser().resolve()

def _check_inside(candidate: Path, roots: Sequence[Path]) -> Path:
    """Ensure *candidate* is a child of one of *roots* (string‑prefix test)."""
    resolved = candidate.expanduser().resolve()
    if not any(str(resolved).startswith(str(root)) for root in roots):
        raise ValueError(
            f"Access denied – {resolved} outside allowed roots: "
            + ", ".join(str(r) for r in roots)
        )
    return resolved

def _file_meta(p: Path) -> Dict[str, Any]:
    st = p.stat()
    return {
        "size": st.st_size,
        "created": datetime.fromtimestamp(st.st_ctime).isoformat(sep=" ", timespec="seconds"),
        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(sep=" ", timespec="seconds"),
        "accessed": datetime.fromtimestamp(st.st_atime).isoformat(sep=" ", timespec="seconds"),
        "isDirectory": p.is_dir(),
        "isFile": p.is_file(),
        "permissions": oct(st.st_mode & 0o777)[-3:],
    }

def _unified(a: str, b: str, fname: str) -> str:
    return "".join(
        difflib.unified_diff(
            a.splitlines(keepends=True),
            b.splitlines(keepends=True),
            fromfile=fname,
            tofile=fname,
            fromfiledate="original",
            tofiledate="modified",
            lineterm="",
        )
    )

def _apply(content: str, edits: List[Dict[str, str]], fname: str) -> tuple[str, str]:
    work = content.replace("\r\n", "\n")
    for e in edits:
        old = e["oldText"].replace("\r\n", "\n")
        new = e["newText"].replace("\r\n", "\n")
        if old not in work:
            raise ValueError(f"Could not find exact match for edit:\n{old}")
        work = work.replace(old, new)
    return work, _unified(content, work, fname)

def _find_files_by_partial_name(roots: List[str], pattern: str, excludes: List[str] = []) -> List[str]:
    pattern = pattern.lower()
    results = []
    for root in roots:
        root_path = Path(root).resolve()
        for p in root_path.rglob("*"):
            rel = p.relative_to(root_path)
            if any(rel.match(ex) for ex in excludes):
                continue
            if p.is_file() and pattern in p.name.lower():
                results.append(str(p.resolve()))
    return results

def _read_file_content(p: Path, partial: bool) -> str:
    suffix = p.suffix.lower()
    if suffix == '.json':
        content = json.loads(p.read_text(encoding='utf-8'))
        formatted_content = json.dumps(content, indent=2, ensure_ascii=False)
        if partial:
            lines = formatted_content.split('\n')
            if len(lines) > 20:
                return '\n'.join(lines[:20]) + '\n... (truncated)'
            else:
                return formatted_content
        else:
            return formatted_content
    elif suffix in ['.csv', '.tsv']:
        df = pd.read_csv(p, sep='\t' if suffix == '.tsv' else ',')
        if partial:
            return df.head(5).to_string()
        else:
            return df.head(20).to_string()
    elif suffix in ['.txt', '.md', '.py', '.log']:
        content = p.read_text(encoding='utf-8')
        if partial:
            lines = content.split('\n')
            if len(lines) > 50:
                return '\n'.join(lines[:50]) + '\n... (truncated)'
            else:
                return content
        else:
            return content
    elif suffix == '.pdf' and PyPDF2:
        reader = PyPDF2.PdfReader(str(p))
        if partial:
            return "\n".join(page.extract_text() or "" for page in reader.pages[:3])
        else:
            return "\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix in ['.jpg', '.jpeg', '.png'] and Image:
        with Image.open(p) as img:
            return f"Image {p.name}: size={img.size}, mode={img.mode}, format={img.format}"
    else:
        return p.read_bytes()[:256].hex() + "..."

def parse_content_as_csv(content: str) -> list[list[str]]:
    """
    content가 어떤 포맷일지 모를 때 csv로 파싱할 수 있도록 유연하게 처리
    """
    # 1. JSON 배열 형태 시도
    try:
        rows = json.loads(content)
        if isinstance(rows, list) and all(isinstance(row, list) for row in rows):
            return rows
    except json.JSONDecodeError:
        pass

    # 2. CSV 텍스트 형태로 직접 파싱 시도
    try:
        rows = list(csv.reader(io.StringIO(content)))
        if rows:
            return rows
    except Exception:
        pass

    # 3. 실패
    raise ValueError("Unable to parse content as either JSON array or CSV text.")


def _write_file_by_type(p: Path, content: str, data_type: str) -> None:
    """Write content to the given path based on data type."""
    if data_type == "text":
        p.write_text(content, encoding="utf-8")

    elif data_type == "json":
        escaped = content.encode('utf-8').decode('unicode_escape')
        obj = json.loads(escaped)
        p.write_text(json.dumps(obj, indent=2), encoding="utf-8")

    elif data_type == "binary":
        raw_bytes = base64.b64decode(content)
        p.write_bytes(raw_bytes)

    elif data_type == "csv":
        rows = parse_content_as_csv(content)
        with p.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
    else:
        raise ValueError(f"Unsupported data_type: {data_type}")