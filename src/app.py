#!/usr/bin/env python3
"""External A2A agent demonstrating approval before protected tool execution."""

import asyncio
import json
import os
import re
import time
import uuid

import anthropic
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
MODEL = os.environ.get("HIL_MODEL") or os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
CLIENT = anthropic.Anthropic(timeout=90.0)

SYSTEM = """You are an external A2A agent demonstrating human approval for tools.
When the user asks to inspect or list a filesystem directory, call list_directory.
Never invent directory contents and never claim a tool ran without a tool result.
After receiving a tool result, clearly state whether approval was received or denied and summarize the result concisely."""

TOOLS = [{
    "name": "list_directory",
    "description": "List the direct children of a filesystem directory. This tool requires human approval before execution.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute directory path, such as /."},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}]

# Demo-only in-memory state. Use Redis/PostgreSQL in production.
PENDING_BY_CONTEXT: dict[str, dict] = {}


def public_base(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}"


@app.get("/.well-known/agent.json")
@app.get("/.well-known/agent-card.json")
async def agent_card(request: Request):
    return {
        "name": "A2A Tool Approval Example",
        "description": "External A2A agent that pauses protected tool execution for approval in SAM Chat.",
        "url": public_base(request) + "/",
        "version": "1.0.1",
        "protocolVersion": "0.3.0",
        "capabilities": {"streaming": True, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{
            "id": "tool-approval-example",
            "name": "Tool Approval Example",
            "description": "Requests approval before executing a protected filesystem tool.",
            "tags": ["a2a", "hil", "hitl", "approval"],
            "examples": ["Please run ls / and show me the output."],
        }],
    }


def text_from(message: dict) -> str:
    return "\n".join(
        str(part.get("text", ""))
        for part in message.get("parts", [])
        if part.get("kind") == "text" or "text" in part
    )


def content_dicts(response) -> list[dict]:
    return [block.model_dump(exclude_none=True) for block in response.content]


def response_text(response) -> str:
    text = "\n".join(block.text for block in response.content if block.type == "text" and block.text.strip())
    return text or "The model returned no text."


def run_model(messages: list[dict], *, allow_tools: bool = True):
    args = {"model": MODEL, "max_tokens": 2048, "system": SYSTEM, "messages": messages}
    if allow_tools:
        args["tools"] = TOOLS
    return CLIENT.messages.create(**args)


def execute_approved_tool(name: str, arguments: dict) -> str:
    if name != "list_directory":
        return json.dumps({"error": f"Unsupported tool: {name}"})
    path = str(arguments.get("path", "/"))
    if path != "/":
        return json.dumps({"error": "This example permits only the approved path /."})
    try:
        return json.dumps({"path": path, "entries": sorted(os.listdir(path))})
    except Exception as exc:
        return json.dumps({"path": path, "error": str(exc)})


def classify_decision(text: str):
    value = re.sub(r"[^a-z\s]", " ", text.strip().lower())
    value = " ".join(value.split())
    denial_patterns = (
        r"^(no|deny|denied|reject|rejected|cancel|cancelled|canceled)$",
        r"^(no|do not|don t|please do not|please don t) (approve|proceed|execute|run|confirm)( it)?$",
    )
    approval_patterns = (
        r"^(yes|approve|approved|proceed|confirm|confirmed)$",
        r"^(yes please|yes approve|go ahead|please proceed|please approve|approve it|run it|execute it)$",
    )
    if any(re.fullmatch(pattern, value) for pattern in denial_patterns):
        return False
    if any(re.fullmatch(pattern, value) for pattern in approval_patterns):
        return True
    return None


def status_message(task_id: str, context_id: str, state: str, text: str) -> dict:
    return {
        "state": state,
        "message": {
            "role": "agent",
            "parts": [{"kind": "text", "text": text}],
            "messageId": "msg-" + str(uuid.uuid4()),
            "taskId": task_id,
            "contextId": context_id,
            "kind": "message",
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def make_task(task_id: str, context_id: str, state: str, text: str, history=None) -> dict:
    return {
        "id": task_id,
        "contextId": context_id,
        "kind": "task",
        "status": status_message(task_id, context_id, state, text),
        "history": history or [],
        "artifacts": [],
    }


async def resume_pending(request_id, context_id: str, text: str, pending: dict) -> dict:
    decision = classify_decision(text)
    if decision is None:
        task = make_task(
            str(request_id), context_id, "input-required",
            "Please reply **yes, approve** to execute the pending tool, or **deny** to cancel it.",
        )
        return {"jsonrpc": "2.0", "id": request_id, "result": task}

    tool_results = []
    for call in pending["tool_calls"]:
        if decision:
            content = execute_approved_tool(call["name"], call["input"])
            is_error = False
        else:
            content = "The user denied this tool invocation. Do not call it again; acknowledge the denial."
            is_error = True
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": call["id"],
            "content": content,
            "is_error": is_error,
        })

    messages = pending["messages"] + [
        {"role": "assistant", "content": pending["assistant_content"]},
        {"role": "user", "content": tool_results},
    ]
    response = await asyncio.to_thread(run_model, messages, allow_tools=False)
    task = make_task(str(request_id), context_id, "completed", response_text(response))
    PENDING_BY_CONTEXT.pop(context_id, None)
    return {"jsonrpc": "2.0", "id": request_id, "result": task}


async def start_task(request_id, message: dict) -> dict:
    context_id = str(message.get("contextId") or "hil-context-" + str(uuid.uuid4()))
    text = text_from(message)
    pending = PENDING_BY_CONTEXT.get(context_id)
    if pending:
        return await resume_pending(request_id, context_id, text, pending)

    messages = [{"role": "user", "content": text}]
    try:
        response = await asyncio.to_thread(run_model, messages)
    except Exception as exc:
        task = make_task(str(request_id), context_id, "failed", f"LLM request failed: {exc}")
        return {"jsonrpc": "2.0", "id": request_id, "result": task}

    tool_calls = [
        {"id": block.id, "name": block.name, "input": block.input}
        for block in response.content
        if block.type == "tool_use"
    ]
    if not tool_calls:
        task = make_task(str(request_id), context_id, "completed", response_text(response), [message])
        return {"jsonrpc": "2.0", "id": request_id, "result": task}

    pending_task_id = "hil-task-" + str(uuid.uuid4())
    PENDING_BY_CONTEXT[context_id] = {
        "task_id": pending_task_id,
        "messages": messages,
        "assistant_content": content_dicts(response),
        "tool_calls": tool_calls,
    }
    calls = ", ".join(f"{call['name']}({json.dumps(call['input'], sort_keys=True)})" for call in tool_calls)
    prompt = f"The LLM requested tool execution: `{calls}`. Reply **yes, approve** or **deny** in this chat."
    task = make_task(pending_task_id, context_id, "input-required", prompt, [message])
    return {"jsonrpc": "2.0", "id": request_id, "result": task}


@app.post("/")
@app.post("/message:send")
@app.post("/message:stream")
async def a2a(request: Request):
    body = await request.json()
    method = str(body.get("method", "")).lower()
    if method not in {"message/send", "sendmessage", "message/stream", "streammessage"} and request.url.path not in {"/message:send", "/message:stream"}:
        return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": "Method not found"}})

    result = await start_task(body.get("id"), body.get("params", {}).get("message", body.get("message", {})))
    if "stream" not in method and not request.url.path.endswith(":stream"):
        return JSONResponse(result)

    async def events():
        task = result["result"]
        if task.get("status", {}).get("state") == "input-required":
            submitted = {**task, "status": {"state": "submitted", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}
            update = {
                "kind": "status-update",
                "taskId": task["id"],
                "contextId": task["contextId"],
                "status": task["status"],
                "final": True,
            }
            yield "data: " + json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": submitted}) + "\n\n"
            yield "data: " + json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": update}) + "\n\n"
        else:
            yield "data: " + json.dumps(result) + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {"ok": True, "model": MODEL, "pending": len(PENDING_BY_CONTEXT)}
