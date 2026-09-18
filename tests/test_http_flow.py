import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app


class Block:
    def __init__(self, block_type, **values):
        self.type = block_type
        self.__dict__.update(values)

    def model_dump(self, exclude_none=True):
        return {"type": self.type, **{key: value for key, value in self.__dict__.items() if key != "type"}}


def payload(context, text, method="message/send"):
    return {
        "jsonrpc": "2.0",
        "id": "request-id",
        "method": method,
        "params": {
            "message": {
                "role": "user",
                "kind": "message",
                "messageId": "message-id",
                "contextId": context,
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }


def install_model(monkeypatch):
    def fake_model(messages, allow_tools=True):
        if allow_tools:
            return SimpleNamespace(content=[Block("tool_use", id="tool-1", name="list_directory", input={"path": "/"})])
        return SimpleNamespace(content=[Block("text", text="finished")])

    monkeypatch.setattr(app, "run_model", fake_model)


def test_http_approval_executes_only_after_decision(monkeypatch):
    app.PENDING_BY_CONTEXT.clear()
    install_model(monkeypatch)
    executions = []
    monkeypatch.setattr(app, "execute_approved_tool", lambda name, arguments: executions.append((name, arguments)) or '{"entries":["tmp"]}')
    client = TestClient(app.app)

    proposed = client.post("/message:send", json=payload("approve", "list /"))
    assert proposed.status_code == 200
    assert proposed.json()["result"]["status"]["state"] == "input-required"
    assert executions == []

    ambiguous = client.post("/message:send", json=payload("approve", "maybe"))
    assert ambiguous.json()["result"]["status"]["state"] == "input-required"
    assert executions == []

    approved = client.post("/message:send", json=payload("approve", "yes, approve"))
    assert approved.json()["result"]["status"]["state"] == "completed"
    assert executions == [("list_directory", {"path": "/"})]
    assert app.PENDING_BY_CONTEXT == {}


def test_http_denial_never_executes(monkeypatch):
    app.PENDING_BY_CONTEXT.clear()
    install_model(monkeypatch)
    executions = []
    monkeypatch.setattr(app, "execute_approved_tool", lambda name, arguments: executions.append((name, arguments)) or '{}')
    client = TestClient(app.app)

    proposed = client.post("/message:send", json=payload("deny", "list /"))
    assert proposed.json()["result"]["status"]["state"] == "input-required"
    denied = client.post("/message:send", json=payload("deny", "don't approve"))
    assert denied.json()["result"]["status"]["state"] == "completed"
    assert executions == []
    assert app.PENDING_BY_CONTEXT == {}


def test_stream_returns_submitted_then_input_required(monkeypatch):
    app.PENDING_BY_CONTEXT.clear()
    install_model(monkeypatch)
    client = TestClient(app.app)

    response = client.post("/message:stream", json=payload("stream", "list /", "message/stream"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert len(events) == 2
    assert events[0]["result"]["status"]["state"] == "submitted"
    assert events[1]["result"]["kind"] == "status-update"
    assert events[1]["result"]["status"]["state"] == "input-required"
    assert events[1]["result"]["final"] is True
