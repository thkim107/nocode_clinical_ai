"""Chat endpoint with OpenRouter API + MCP tool integration + user approval."""

import json
import logging
import os
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from chat.mcp_client import mcp_call_tool, mcp_list_tools
from audit_logger import audit_log
from telemetry import (
    complete_tool_call,
    deny_tool_calls,
    mark_tool_approved,
    record_event,
    record_llm_call,
    record_tool_requested,
    set_workflow_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
CHAT_MODEL = os.getenv("CHAT_MODEL", "anthropic/claude-sonnet-4-6")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_TIMEOUT = float(os.getenv("OPENROUTER_TIMEOUT", "600"))
MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "20"))

MCP_SERVERS = {
    "db-connector": "Clinical database queries (synthea, cdm, kmimic, mimiciv, inspire)",
    "file-system": "File read/write/search operations",
    "ml-system": "Machine learning pipeline (EDA, feature selection, model training)",
    "docx-system": "Word document creation and editing",
}

SYSTEM_PROMPT = """You are a clinical research scientist — not merely an assistant, but an independent researcher who drives studies forward.

## Your identity
- You design research, form hypotheses, choose methodologies, and execute analyses with the autonomy of a lead investigator.
- When a user presents a research topic, you proactively propose study designs, identify relevant variables, suggest statistical approaches, and anticipate potential pitfalls — rather than waiting for step-by-step instructions.
- You think critically: question assumptions, flag confounders, and recommend sensitivity analyses.

## Your capabilities
You have direct access to the following tools via MCP servers:
- **db-connector**: Query clinical databases (synthea, cdm, kmimic, mimiciv, inspire). Always specify the database name.
- **file-system**: Read, write, and search files under /app/data.
- **ml-system**: Run ML analysis pipelines — EDA, feature selection, model training & evaluation.
- **docx-system**: Create and edit Word documents (research reports, IRB protocols, TRIPOD+AI reports).

## How you work
1. **Take initiative**: When given a research question, outline the full approach (data source → cohort selection → variables → analysis plan → expected outputs) before asking for confirmation.
2. **Be thorough**: Run exploratory queries to understand the data before jumping to analysis. Check distributions, missing values, and sample sizes.
3. **Document everything**: Save intermediate results as CSV files, produce well-structured Word reports, and keep a clear audit trail.
4. **Communicate like a researcher**: Use precise terminology, cite statistical rationale, and present results with context (confidence intervals, effect sizes, limitations).
5. **Chain tools effectively**: Combine database queries, file operations, ML pipelines, and document generation in a single workflow when appropriate.

Present all results clearly with proper formatting."""


class ChatRequest(BaseModel):
    messages: list[dict]  # supports both simple text and content blocks (tool_use/tool_result)
    system: Optional[str] = None
    enabled_servers: Optional[list[str]] = None
    enabled_tools: Optional[list[str]] = None
    auto_approve_servers: Optional[list[str]] = None  # servers that don't need approval


class ToolApproval(BaseModel):
    tool_use_id: str
    name: str
    input: dict


class ApproveToolsRequest(BaseModel):
    messages: list[dict]  # full conversation history including assistant content blocks
    approved_tools: list[ToolApproval]
    enabled_servers: Optional[list[str]] = None
    enabled_tools: Optional[list[str]] = None
    auto_approve_servers: Optional[list[str]] = None
    system: Optional[str] = None


class DenyToolsRequest(BaseModel):
    tool_use_ids: list[str]


def _convert_mcp_tool_to_openai(tool: dict) -> dict:
    """Convert MCP tool definition to OpenAI function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": f"{tool['_server']}__{tool['name']}",
            "description": f"[{tool['_server']}] {tool.get('description', '')}",
            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
        },
    }


def _convert_messages_to_openai(messages: list[dict], system: str) -> list[dict]:
    """Convert Anthropic-style messages to OpenAI-compatible format for OpenRouter."""
    openai_messages = [{"role": "system", "content": system}]

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            openai_messages.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            if role == "assistant":
                text_parts = []
                tool_calls = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block["input"]),
                            },
                        })
                assistant_msg = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                openai_messages.append(assistant_msg)

            elif role == "user":
                # Could be tool_result blocks or mixed content
                tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                other_blocks = [b for b in content if not (isinstance(b, dict) and b.get("type") == "tool_result")]

                for tr in tool_results:
                    tr_content = tr.get("content", "")
                    if isinstance(tr_content, list):
                        tr_content = "\n".join(c.get("text", str(c)) for c in tr_content)
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_use_id"],
                        "content": str(tr_content),
                    })

                if other_blocks:
                    text_parts = []
                    for b in other_blocks:
                        if isinstance(b, dict) and b.get("type") == "text":
                            text_parts.append(b["text"])
                        elif isinstance(b, str):
                            text_parts.append(b)
                    if text_parts:
                        openai_messages.append({"role": "user", "content": "\n".join(text_parts)})

    return openai_messages


def _convert_openai_response_to_anthropic(response: dict) -> dict:
    """Convert OpenRouter (OpenAI-format) response to Anthropic-style format."""
    choice = response.get("choices", [{}])[0]
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason", "stop")

    # Map finish_reason to Anthropic stop_reason
    stop_reason_map = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}
    stop_reason = stop_reason_map.get(finish_reason, "end_turn")

    content_blocks = []

    # Add text content
    text = message.get("content")
    if text:
        content_blocks.append({"type": "text", "text": text})

    # Add tool calls
    tool_calls = message.get("tool_calls", [])
    for tc in tool_calls:
        func = tc.get("function", {})
        try:
            arguments = json.loads(func.get("arguments", "{}"))
        except json.JSONDecodeError:
            arguments = {}
        content_blocks.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": func.get("name", ""),
            "input": arguments,
        })

    if tool_calls and stop_reason == "end_turn":
        stop_reason = "tool_use"

    # Map usage
    usage_in = response.get("usage", {})
    input_tokens = usage_in.get("prompt_tokens")
    output_tokens = usage_in.get("completion_tokens")
    total_tokens = usage_in.get("total_tokens")
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": (usage_in.get("prompt_tokens_details") or {}).get("cached_tokens"),
        "reasoning_tokens": (usage_in.get("completion_tokens_details") or {}).get("reasoning_tokens"),
    }

    return {
        "content": content_blocks,
        "stop_reason": stop_reason,
        "usage": usage,
    }


async def _gather_tools(enabled_servers, enabled_tools):
    """Gather tools from MCP servers based on filters."""
    servers_to_use = enabled_servers if enabled_servers else list(MCP_SERVERS.keys())
    openai_tools = []
    tool_server_map = {}
    for server in servers_to_use:
        if server not in MCP_SERVERS:
            continue
        try:
            tools = await mcp_list_tools(server)
            for t in tools:
                t["_server"] = server
                converted = _convert_mcp_tool_to_openai(t)
                tool_name = converted["function"]["name"]
                if enabled_tools and tool_name not in enabled_tools:
                    continue
                openai_tools.append(converted)
                tool_server_map[tool_name] = (server, t["name"])
        except Exception:
            continue
    return openai_tools, tool_server_map


async def _execute_tool(server: str, real_name: str, tool_input: dict) -> tuple[str, bool, Optional[str]]:
    """Execute one MCP tool and return text plus an explicit outcome."""
    try:
        mcp_result = await mcp_call_tool(server, real_name, tool_input)
        result_text = ""
        if "content" in mcp_result:
            for c in mcp_result["content"]:
                if isinstance(c, dict) and "text" in c:
                    result_text += c["text"]
                elif isinstance(c, str):
                    result_text += c
        else:
            result_text = json.dumps(mcp_result)
        success = not bool(mcp_result.get("isError"))
        error = None if success else result_text[:4000]
        if not success:
            logger.warning(f"Tool {server}/{real_name} returned error: {result_text[:200]}")
        return result_text, success, error
    except Exception as e:
        logger.error(f"Tool {server}/{real_name} execution failed: {e}", exc_info=True)
        return f"Error calling tool: {str(e)}", False, str(e)


async def _call_openrouter(messages, system, openai_tools, iteration: int):
    """Call OpenRouter API (OpenAI-compatible) and return Anthropic-style result."""
    import time as _t
    t0 = _t.time()
    call_id = str(uuid.uuid4())

    openai_messages = _convert_messages_to_openai(messages, system)
    api_payload = {
        "model": CHAT_MODEL,
        "max_tokens": 65536,
        "messages": openai_messages,
    }
    if openai_tools:
        api_payload["tools"] = openai_tools

    result_data = None
    anthropic_result = None
    error_text = None
    status_code = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(OPENROUTER_TIMEOUT)) as client:
            resp = await client.post(
                OPENROUTER_API_URL,
                json=api_payload,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "content-type": "application/json",
                },
            )
            status_code = resp.status_code
            if resp.status_code != 200:
                error_text = resp.text
                return None, error_text, call_id
            result_data = resp.json()
            anthropic_result = _convert_openai_response_to_anthropic(result_data)
            return anthropic_result, None, call_id
    except Exception as e:
        logger.error(f"OpenRouter API call failed: {e}")
        error_text = f"OpenRouter API call failed: {str(e)}"
        return None, error_text, call_id
    finally:
        duration_ms = int((_t.time() - t0) * 1000)
        resp_summary = None
        if anthropic_result:
            resp_summary = {
                "stop_reason": anthropic_result.get("stop_reason"),
                "content_types": [b.get("type") for b in anthropic_result.get("content", [])],
                "usage": anthropic_result.get("usage"),
            }
        await audit_log(
            "platform", "openrouter", "v1/chat/completions", "POST",
            request_summary={"model": CHAT_MODEL, "message_count": len(messages), "tool_count": len(openai_tools) if openai_tools else 0},
            response_status=status_code,
            response_summary=resp_summary,
            duration_ms=duration_ms,
            error=error_text,
        )
        usage = anthropic_result.get("usage", {}) if anthropic_result else {}
        response_chars = sum(
            len(block.get("text", ""))
            for block in (anthropic_result or {}).get("content", [])
            if block.get("type") == "text"
        )
        await record_llm_call(
            call_id=call_id, provider="openrouter", model=CHAT_MODEL,
            duration_ms=duration_ms, input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"), total_tokens=usage.get("total_tokens"),
            cached_input_tokens=usage.get("cached_input_tokens"),
            reasoning_tokens=usage.get("reasoning_tokens"),
            finish_reason=(anthropic_result or {}).get("stop_reason"),
            request_chars=len(json.dumps(api_payload, ensure_ascii=False, default=str)),
            response_chars=response_chars, message_count=len(messages),
            tool_definition_count=len(openai_tools) if openai_tools else 0,
            iteration=iteration, status="succeeded" if error_text is None else "failed",
            error=error_text, operation="chat.llm_iteration",
        )


async def _run_tool_loop(current_messages, system, openai_tools, tool_server_map, auto_servers, max_iterations=MAX_TOOL_ITERATIONS):
    """Core agentic loop: call LLM, execute tools, repeat. Yields SSE events."""
    import time as _time
    msg_count = len(current_messages)
    msg_size = len(json.dumps(current_messages, default=str))
    logger.info(f"Tool loop started: {msg_count} messages, ~{msg_size} bytes payload")

    for iteration in range(max_iterations):
        logger.info(f"Iteration {iteration}: calling OpenRouter API ({len(current_messages)} messages)")
        t0 = _time.time()
        result, error, llm_call_id = await _call_openrouter(current_messages, system, openai_tools, iteration)
        api_elapsed = _time.time() - t0
        logger.info(f"Iteration {iteration}: OpenRouter API responded in {api_elapsed:.1f}s")

        if error:
            await set_workflow_status(
                "failed",
                metadata={"failure_phase": "chat.llm_iteration", "iteration": iteration},
            )
            logger.warning(f"OpenRouter API error on iteration {iteration} (after {api_elapsed:.1f}s): {error[:500]}")
            yield f"data: {json.dumps({'type': 'error', 'content': error[:2000]})}\n\n"
            return

        stop_reason = result.get("stop_reason", "end_turn")
        content_blocks = result.get("content", [])
        tool_uses = [b for b in content_blocks if b.get("type") == "tool_use"]
        text_blocks = [b for b in content_blocks if b.get("type") == "text"]
        tool_names = [tu["name"] for tu in tool_uses]

        logger.info(f"Iteration {iteration}: stop_reason={stop_reason}, text_blocks={len(text_blocks)}, tool_uses={len(tool_uses)}, tools={tool_names}")

        for tb in text_blocks:
            yield f"data: {json.dumps({'type': 'text', 'content': tb['text']})}\n\n"

        # If hit max_tokens, ask the model to continue
        if stop_reason == "max_tokens":
            current_messages.append({"role": "assistant", "content": content_blocks})
            current_messages.append({"role": "user", "content": "Continue from where you left off."})
            continue

        if not tool_uses or stop_reason != "tool_use":
            # No more tools — if no text was produced after tool execution, generate a fallback
            if not text_blocks and iteration > 0:
                logger.warning(f"No text in response after tool execution on iteration {iteration}, stop_reason={stop_reason}")
                yield f"data: {json.dumps({'type': 'text', 'content': '도구 실행 결과를 확인했습니다. 응답을 생성하는 중 문제가 발생했습니다. 다시 시도해 주세요.'})}\n\n"
            final_messages = current_messages + [{"role": "assistant", "content": content_blocks}]
            yield f"data: {json.dumps({'type': 'done', 'conversation': final_messages})}\n\n"
            return

        # Split tools into auto-approved and pending
        auto_tools = []
        pending_tools = []
        for tu in tool_uses:
            full_name = tu["name"]
            server = full_name.split("__")[0] if "__" in full_name else ""
            mapped_server, real_name = tool_server_map.get(
                full_name, (server, full_name.split("__", 1)[-1])
            )
            approval_mode = "auto" if server in auto_servers else "manual"
            await record_tool_requested(
                provider_tool_call_id=tu["id"], llm_call_id=llm_call_id,
                server=mapped_server, tool_name=real_name, iteration=iteration,
                approval_mode=approval_mode, tool_input=tu["input"],
            )
            if approval_mode == "auto":
                auto_tools.append(tu)
            else:
                pending_tools.append(tu)

        # If there are pending tools, send them for approval and STOP
        if pending_tools:
            auto_results = []
            for tu in auto_tools:
                full_name = tu["name"]
                await mark_tool_approved(tu["id"])
                t_tool = _time.time()
                if full_name in tool_server_map:
                    server, real_name = tool_server_map[full_name]
                    yield f"data: {json.dumps({'type': 'tool_auto_executed', 'name': full_name, 'input': tu['input']})}\n\n"
                    result_text, success, tool_error = await _execute_tool(server, real_name, tu["input"])
                else:
                    result_text = f"Unknown tool: {full_name}"
                    success, tool_error = False, result_text
                tool_duration_ms = int((_time.time() - t_tool) * 1000)
                await complete_tool_call(
                    tu["id"], duration_ms=tool_duration_ms, success=success,
                    output=result_text, error=tool_error,
                )
                yield f"data: {json.dumps({'type': 'tool_result', 'name': full_name, 'result': result_text[:3000]})}\n\n"
                auto_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": result_text,
                })

            pending_info = []
            for tu in pending_tools:
                full_name = tu["name"]
                server = full_name.split("__")[0] if "__" in full_name else ""
                pending_info.append({
                    "tool_use_id": tu["id"],
                    "name": full_name,
                    "server": server,
                    "input": tu["input"],
                })

            pending_conversation = list(current_messages)
            pending_conversation.append({"role": "assistant", "content": content_blocks})
            if auto_results:
                pending_conversation.append({"role": "user", "content": auto_results})

            await set_workflow_status(
                "waiting_approval",
                metadata={"pending_tool_count": len(pending_tools), "iteration": iteration},
            )
            await record_event(
                "tool_approval_requested", phase="chat.tool_approval", attempt=iteration + 1,
                metadata={"pending_tool_count": len(pending_tools)},
            )
            yield f"data: {json.dumps({'type': 'tool_calls_pending', 'calls': pending_info, 'assistant_content': content_blocks, 'auto_results': auto_results, 'conversation': pending_conversation})}\n\n"
            return

        # All tools are auto-approved — execute all
        current_messages.append({"role": "assistant", "content": content_blocks})
        tool_results = []

        for idx, tu in enumerate(tool_uses):
            full_name = tu["name"]
            logger.info(f"Iteration {iteration}: executing tool {idx+1}/{len(tool_uses)}: {full_name}")
            yield f"data: {json.dumps({'type': 'tool_auto_executed', 'name': full_name, 'input': tu['input']})}\n\n"

            await mark_tool_approved(tu["id"])
            t_tool = _time.time()
            if full_name in tool_server_map:
                server, real_name = tool_server_map[full_name]
                result_text, success, tool_error = await _execute_tool(server, real_name, tu["input"])
            else:
                result_text = f"Unknown tool: {full_name}"
                success, tool_error = False, result_text
            tool_elapsed = _time.time() - t_tool
            await complete_tool_call(
                tu["id"], duration_ms=int(tool_elapsed * 1000), success=success,
                output=result_text, error=tool_error,
            )
            logger.info(f"Iteration {iteration}: tool {full_name} completed in {tool_elapsed:.1f}s, result_len={len(result_text)}")

            yield f"data: {json.dumps({'type': 'tool_result', 'name': full_name, 'result': result_text[:3000]})}\n\n"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": result_text,
            })

        total_result_size = sum(len(tr["content"]) for tr in tool_results)
        logger.info(f"Iteration {iteration}: all {len(tool_results)} tools done, total result size={total_result_size}")
        current_messages.append({"role": "user", "content": tool_results})

    # max_iterations exhausted
    logger.warning(f"Tool loop reached max iterations ({max_iterations})")
    await set_workflow_status(
        "limit_reached", metadata={"max_tool_iterations": max_iterations}
    )
    await record_event(
        "max_tool_iterations", phase="chat.tool_loop", attempt=max_iterations,
        metadata={"max_iterations": max_iterations},
    )
    yield f"data: {json.dumps({'type': 'text', 'content': f'도구 호출 반복 횟수가 최대치({max_iterations}회)에 도달하여 중단되었습니다. 이어서 진행하려면 계속 요청해 주세요.'})}\n\n"
    yield f"data: {json.dumps({'type': 'done', 'conversation': current_messages})}\n\n"


@router.get("/tools")
async def list_available_tools():
    all_tools = []
    for server in MCP_SERVERS:
        try:
            tools = await mcp_list_tools(server)
            for t in tools:
                all_tools.append({
                    "server": server,
                    "name": t["name"],
                    "description": t.get("description", ""),
                })
        except Exception as e:
            all_tools.append({"server": server, "error": str(e)})
    return {"tools": all_tools}


@router.post("/completions")
async def chat_completions(req: ChatRequest):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")

    openai_tools, tool_server_map = await _gather_tools(req.enabled_servers, req.enabled_tools)
    messages = list(req.messages)
    system = req.system or SYSTEM_PROMPT
    auto_servers = set(req.auto_approve_servers or [])

    async def generate():
        current_messages = list(messages)
        try:
            async for event in _run_tool_loop(current_messages, system, openai_tools, tool_server_map, auto_servers):
                yield event
        except Exception as e:
            await set_workflow_status("failed", metadata={"failure_phase": "chat.stream"})
            await record_event("stream_failed", phase="chat.stream")
            logger.error(f"Stream error in completions: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': f'Internal error: {str(e)}'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/approve-tools")
async def approve_tools(req: ApproveToolsRequest):
    """Execute approved tools and continue the conversation."""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")

    openai_tools, tool_server_map = await _gather_tools(req.enabled_servers, req.enabled_tools)
    system = req.system or SYSTEM_PROMPT
    auto_servers = set(req.auto_approve_servers or [])

    async def generate():
        import time as _time
        try:
            # Execute the approved tools
            logger.info(f"approve-tools: executing {len(req.approved_tools)} approved tools")
            tool_results = []
            for idx, tool in enumerate(req.approved_tools):
                full_name = tool.name
                logger.info(f"approve-tools: executing tool {idx+1}/{len(req.approved_tools)}: {full_name}")
                yield f"data: {json.dumps({'type': 'tool_executing', 'name': full_name, 'input': tool.input})}\n\n"

                server_hint = full_name.split("__")[0] if "__" in full_name else ""
                mapped_server, real_name = tool_server_map.get(
                    full_name, (server_hint, full_name.split("__", 1)[-1])
                )
                await record_tool_requested(
                    provider_tool_call_id=tool.tool_use_id, llm_call_id=None,
                    server=mapped_server, tool_name=real_name, iteration=-1,
                    approval_mode="manual", tool_input=tool.input,
                )
                await mark_tool_approved(tool.tool_use_id)
                t_tool = _time.time()
                if full_name in tool_server_map:
                    server, real_name = tool_server_map[full_name]
                    result_text, success, tool_error = await _execute_tool(server, real_name, tool.input)
                else:
                    result_text = f"Unknown tool: {full_name}"
                    success, tool_error = False, result_text
                tool_elapsed = _time.time() - t_tool
                await complete_tool_call(
                    tool.tool_use_id, duration_ms=int(tool_elapsed * 1000), success=success,
                    output=result_text, error=tool_error,
                )
                logger.info(f"approve-tools: tool {full_name} completed in {tool_elapsed:.1f}s, result_len={len(result_text)}")

                yield f"data: {json.dumps({'type': 'tool_result', 'name': full_name, 'result': result_text[:3000]})}\n\n"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool.tool_use_id,
                    "content": result_text,
                })

            # Build conversation with tool results and continue
            current_messages = list(req.messages)
            current_messages.append({"role": "user", "content": tool_results})
            logger.info(f"approve-tools: continuing with {len(current_messages)} messages")

            async for event in _run_tool_loop(current_messages, system, openai_tools, tool_server_map, auto_servers):
                yield event
        except Exception as e:
            await set_workflow_status("failed", metadata={"failure_phase": "chat.approve_tools"})
            await record_event("stream_failed", phase="chat.approve_tools")
            logger.error(f"Stream error in approve-tools: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': f'Internal error: {str(e)}'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/deny-tools")
async def deny_tools(req: DenyToolsRequest):
    """Record explicit denial of pending tool calls for the current run."""
    await deny_tool_calls(req.tool_use_ids)
    await record_event(
        "tools_denied", phase="chat.tool_approval",
        metadata={"denied_tool_count": len(req.tool_use_ids)},
    )
    return {"denied": len(req.tool_use_ids)}
