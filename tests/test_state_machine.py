import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app


class Block:
    def __init__(self, block_type, **values):
        self.type = block_type
        self.__dict__.update(values)

    def model_dump(self, exclude_none=True):
        return {key: value for key, value in self.__dict__.items() if key != "type" or value is not None} | {"type": self.type}


def message(context, text):
    return {"contextId": context, "parts": [{"kind": "text", "text": text}]}


def test_approval_and_denial(monkeypatch):
    calls = []

    def fake_model(messages, allow_tools=True):
        if allow_tools:
            return SimpleNamespace(content=[Block("tool_use", id="tool-1", name="list_directory", input={"path": "/"})])
        calls.append(messages[-1]["content"][0])
        return SimpleNamespace(content=[Block("text", text="completed")])

    monkeypatch.setattr(app, "run_model", fake_model)
    monkeypatch.setattr(app, "execute_approved_tool", lambda name, arguments: json.dumps({"path": "/", "entries": ["tmp"]}))

    proposed = asyncio.run(app.start_task("request-1", message("approve-context", "list /")))
    assert proposed["result"]["status"]["state"] == "input-required"
    approved = asyncio.run(app.start_task("request-2", message("approve-context", "yes, approve")))
    assert approved["result"]["status"]["state"] == "completed"
    assert calls[-1]["is_error"] is False

    proposed = asyncio.run(app.start_task("request-3", message("deny-context", "list /")))
    assert proposed["result"]["status"]["state"] == "input-required"
    denied = asyncio.run(app.start_task("request-4", message("deny-context", "deny")))
    assert denied["result"]["status"]["state"] == "completed"
    assert calls[-1]["is_error"] is True
    assert "denied" in calls[-1]["content"].lower()
