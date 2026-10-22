"""Lightweight MCP client for calling tools on MCP servers via StreamableHTTP."""

import os
import time as _time

import httpx

from audit_logger import audit_log
from telemetry import current_context, summarize_payload

MCP_ROUTER_URL = os.getenv("MCP_ROUTER_URL", "http://router:8000")
MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT", "600"))


async def mcp_call_tool(server: str, tool_name: str, arguments: dict) -> dict:
    """Call a tool on an MCP server through the router.

    Args:
        server: MCP server name (e.g. 'db-connector', 'file-system')
        tool_name: Tool name to call
        arguments: Tool arguments dict

    Returns:
        Tool result dict
    """
    t0 = _time.time()
    url = f"{MCP_ROUTER_URL}/{server}/mcp"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    trace = current_context()
    if trace.session_id:
        headers["X-Session-ID"] = trace.session_id
    if trace.run_id:
        headers["X-Run-ID"] = trace.run_id
    result = None
    error_msg = None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(MCP_TIMEOUT)) as client:
            # Initialize session
            init_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "file-manager-chat", "version": "1.0"},
                },
            }
            init_resp = await client.post(url, json=init_payload, headers=headers)
            session_id = init_resp.headers.get("mcp-session-id", "")

            call_headers = {**headers}
            if session_id:
                call_headers["Mcp-Session-Id"] = session_id

            # Call tool
            call_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            resp = await client.post(url, json=call_payload, headers=call_headers)
            text = resp.text

            # Parse SSE response
            for line in text.split("\n"):
                if line.startswith("data: "):
                    import json
                    data = json.loads(line[6:])
                    if "result" in data:
                        result = data["result"]
                        break
                    if "error" in data:
                        result = {"error": data["error"]}
                        error_msg = str(data["error"])
                        break

            if result is None:
                result = {"error": "No result received"}
                error_msg = "No result received"
    except Exception as e:
        error_msg = str(e)
        raise
    finally:
        duration_ms = int((_time.time() - t0) * 1000)
        await audit_log(
            "platform", f"mcp:{server}", f"tools/call:{tool_name}", "POST",
            request_summary={
                "server": server,
                "tool": tool_name,
                "run_id": trace.run_id,
                "payload": summarize_payload(arguments),
            },
            response_status=200 if error_msg is None else 500,
            response_summary={
                "run_id": trace.run_id,
                "payload": summarize_payload(result),
            },
            duration_ms=duration_ms,
            error=error_msg,
        )

    return result


async def mcp_list_tools(server: str) -> list:
    """List available tools on an MCP server."""
    t0 = _time.time()
    url = f"{MCP_ROUTER_URL}/{server}/mcp"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    trace = current_context()
    if trace.session_id:
        headers["X-Session-ID"] = trace.session_id
    if trace.run_id:
        headers["X-Run-ID"] = trace.run_id
    tools_result = []
    error_msg = None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            init_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "file-manager-chat", "version": "1.0"},
                },
            }
            init_resp = await client.post(url, json=init_payload, headers=headers)
            session_id = init_resp.headers.get("mcp-session-id", "")

            call_headers = {**headers}
            if session_id:
                call_headers["Mcp-Session-Id"] = session_id

            list_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }
            resp = await client.post(url, json=list_payload, headers=call_headers)

            for line in resp.text.split("\n"):
                if line.startswith("data: "):
                    import json
                    data = json.loads(line[6:])
                    if "result" in data and "tools" in data["result"]:
                        tools_result = data["result"]["tools"]
                        break
    except Exception as e:
        error_msg = str(e)
        raise
    finally:
        duration_ms = int((_time.time() - t0) * 1000)
        await audit_log(
            "platform", f"mcp:{server}", "tools/list", "POST",
            request_summary={"server": server, "run_id": trace.run_id},
            response_status=200 if error_msg is None else 500,
            response_summary={"tool_count": len(tools_result), "run_id": trace.run_id},
            duration_ms=duration_ms,
            error=error_msg,
        )

    return tools_result
