"""File browser endpoints over the shared volume (/app/data)."""

import json
import logging
import os
import shutil

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from files.path_utils import BASE_DIR, resolve_safe_path, sanitize_filename
from files.preview import preview_file

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["files"])

UPLOAD_MAX_BYTES = 100 * 1024 * 1024  # 100MB


@router.get("/ls")
async def list_directory(path: str = Query("", description="Relative path")):
    try:
        dir_path = resolve_safe_path(path)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not dir_path.exists():
        raise HTTPException(status_code=404, detail="Directory not found")
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    items = []
    try:
        for entry in sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            stat = entry.stat()
            items.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size if entry.is_file() else None,
                "modified": stat.st_mtime,
                "extension": entry.suffix.lower() if entry.is_file() else None,
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {"path": path or "/", "items": items}


@router.get("/preview")
async def preview(path: str = Query(..., description="Relative file path")):
    try:
        file_path = resolve_safe_path(path)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    stat = file_path.stat()
    response = preview_file(file_path)
    if isinstance(response, JSONResponse):
        data = response.body
        import json as _json
        parsed = json.loads(data)
        parsed["modified"] = stat.st_mtime
        parsed["size"] = stat.st_size
        parsed["name"] = file_path.name
        return JSONResponse(parsed)
    # For binary responses (images), set cache headers to no-cache
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["X-File-Modified"] = str(stat.st_mtime)
    return response


@router.get("/download")
async def download(path: str = Query(..., description="Relative file path")):
    try:
        file_path = resolve_safe_path(path)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/upload")
async def upload(
    files: list[UploadFile] = File(...),
    path: str = Query("", description="Target directory"),
):
    try:
        dir_path = resolve_safe_path(path)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
        os.chmod(dir_path, 0o777)

    uploaded = []
    for f in files:
        try:
            safe_name = sanitize_filename(f.filename or "upload")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        dest = dir_path / safe_name
        size = 0
        with open(dest, "wb") as out:
            while chunk := await f.read(8192):
                size += len(chunk)
                if size > UPLOAD_MAX_BYTES:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"File too large (max {UPLOAD_MAX_BYTES // 1024 // 1024}MB)")
                out.write(chunk)
        os.chmod(dest, 0o666)
        uploaded.append({"name": safe_name, "size": size})

    return {"uploaded": uploaded}


@router.post("/mkdir")
async def make_directory(path: str = Query(..., description="Directory path to create")):
    try:
        dir_path = resolve_safe_path(path)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if dir_path.exists():
        raise HTTPException(status_code=409, detail="Already exists")

    dir_path.mkdir(parents=True, exist_ok=True)
    os.chmod(dir_path, 0o777)
    return {"created": path}


@router.delete("/delete")
async def delete(path: str = Query(..., description="Path to delete")):
    try:
        target = resolve_safe_path(path)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")

    if target == BASE_DIR.resolve():
        raise HTTPException(status_code=403, detail="Cannot delete root directory")

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"deleted": path}

