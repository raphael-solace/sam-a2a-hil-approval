#!/usr/bin/env python3
"""Exercise the running A2A service with its configured real model endpoint."""

import json
import os
import urllib.request
import uuid

BASE = os.environ.get("A2A_URL", "http://127.0.0.1:8080").rstrip("/")


def payload(context: str, text: str, *, stream: bool = False) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/stream" if stream else "message/send",
        "params": {
            "message": {
                "role": "user",
                "kind": "message",
                "messageId": str(uuid.uuid4()),
                "contextId": context,
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }


def post(path: str, body: dict) -> tuple[str, str]:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read().decode(), response.headers.get_content_type()


def send(context: str, text: str) -> dict:
    raw, _ = post("/message:send", payload(context, text))
    return json.loads(raw)["result"]


def pending_count() -> int:
    return json.load(urllib.request.urlopen(BASE + "/health", timeout=10))["pending"]


def assert_denial(text: str) -> None:
    normalized = text.lower()
    evidence = ("did not", "not executed", "not performed", "no directory listing", "not able", "no directory data")
    assert "denied" in normalized, text
    assert any(phrase in normalized for phrase in evidence), text


prompt = "Please use your filesystem tool to list the root directory / and report the result."

stream_context = "stream-" + str(uuid.uuid4())
raw, content_type = post("/message:stream", payload(stream_context, prompt, stream=True))
events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
assert content_type == "text/event-stream", content_type
assert len(events) == 2, events
submitted, interrupted = [event["result"] for event in events]
assert submitted["status"]["state"] == "submitted", submitted
assert interrupted["kind"] == "status-update", interrupted
assert interrupted["status"]["state"] == "input-required", interrupted
assert interrupted["final"] is True, interrupted
assert "list_directory" in interrupted["status"]["message"]["parts"][0]["text"], interrupted
assert pending_count() == 1
assert_denial(send(stream_context, "deny")["status"]["message"]["parts"][0]["text"])
assert pending_count() == 0

approve_context = "approve-" + str(uuid.uuid4())
proposed = send(approve_context, prompt)
assert proposed["status"]["state"] == "input-required", proposed
assert pending_count() == 1
approved = send(approve_context, "yes, approve")
approved_text = approved["status"]["message"]["parts"][0]["text"]
assert approved["status"]["state"] == "completed", approved
assert "approval" in approved_text.lower() or "approved" in approved_text.lower(), approved_text
assert any(name in approved_text for name in ("tmp", "usr", "etc", "bin")), approved_text
assert pending_count() == 0

deny_context = "deny-" + str(uuid.uuid4())
proposed = send(deny_context, prompt)
assert proposed["status"]["state"] == "input-required", proposed
assert pending_count() == 1
denied = send(deny_context, "don't approve")
denied_text = denied["status"]["message"]["parts"][0]["text"]
assert denied["status"]["state"] == "completed", denied
assert_denial(denied_text)
assert pending_count() == 0

print(json.dumps({
    "stream": [submitted["status"]["state"], interrupted["status"]["state"]],
    "approve": approved["status"]["state"],
    "deny": denied["status"]["state"],
    "pendingAfter": pending_count(),
}, indent=2))
