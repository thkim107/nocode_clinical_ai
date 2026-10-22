# main.py
import asyncio
import os
from typing import Dict, Iterable

import httpx
from fastapi import FastAPI, Request, Response
from starlette.responses import StreamingResponse

app = FastAPI(title="Simple Docker Reverse Proxy")

# 업스트림 MCP 서버 주소.
# 기본: compose 서비스명으로 DNS 해석 (http://<name>:8000).
# k8s 등 서비스명이 다른 환경에서는 MCP_TARGETS 로 덮어쓴다:
#   MCP_TARGETS="file-system=http://research-agent-file-system:8000,ml-system=http://...:8000"
DEFAULT_TARGETS = ("file-system", "ml-system", "docx-system", "db-connector")


def _load_targets() -> Dict[str, str]:
    raw = os.getenv("MCP_TARGETS", "").strip()
    if not raw:
        return {name: f"http://{name}:8000" for name in DEFAULT_TARGETS}
    targets: Dict[str, str] = {}
    for item in raw.split(","):
        name, _, url = item.strip().partition("=")
        if name and url:
            targets[name.strip()] = url.strip().rstrip("/")
    return targets


TARGETS: Dict[str, str] = _load_targets()

# ──────────────────────────────
async def _proxy(
    request: Request,
    target_url: str,
) -> Response:
    timeout_config = httpx.Timeout(300.0)

    async with httpx.AsyncClient(
        timeout=timeout_config,
        follow_redirects=True,
    ) as client:
        req_body = await request.body()

        # stream=True로 스트리밍 활성화
        upstream = await client.request(
            method=request.method,
            url=target_url,
            content=req_body,
            headers={
                k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in request.headers.items()
                if k.lower() not in {"host", "content-length"}
            },
            params=request.query_params,
        )

        # response 헤더 처리
        resp_headers: Dict[str, str] = {}
        for k, v in upstream.headers.items():
            if k.lower() not in {"content-encoding", "transfer-encoding", "connection"}:
                resp_headers[k] = v

        # 항상 스트리밍으로 반환
        return StreamingResponse(
            upstream.aiter_bytes(),
            status_code=upstream.status_code,
            headers=resp_headers,
        )

# ──────────────────────────────
@app.api_route("/{container}/{path:path}", methods=["GET","POST"])
async def reverse_proxy(container: str, path: str, request: Request):
    """
    프록시 엔드포인트.
    ex) /svc_a/api/v1/hello  →  http://svc_a:8000/api/v1/hello
    """
    if container not in TARGETS:
        return Response(status_code=404, content=f"Unknown container: {container}")
    upstream_url = f"{TARGETS[container]}/{path}"

    return await _proxy(request, upstream_url)


@app.get("/")
async def root():
    return {"status": "ok", "targets": sorted(TARGETS)}
