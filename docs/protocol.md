# Protocol Notes

## Required custom behavior

Solace Agent Mesh does not inject its internal HIL tools into an external A2A agent. The external agent must implement approval-aware tool execution.

When the LLM emits a protected tool call:

1. Do not execute the call.
2. Save the complete assistant response and tool-use metadata.
3. Return A2A `input-required`.
4. Interpret the next correlated user message as approval or denial.
5. Execute only after approval.
6. Resume the LLM with the original tool-use block and matching `tool_result`.

## Streaming response

The tested SAM release expects an initial Task followed by a final status update:

```text
data: {"jsonrpc":"2.0","id":"<sam-task>","result":{
  "id":"<external-task>",
  "contextId":"<context>",
  "kind":"task",
  "status":{"state":"submitted"}
}}

data: {"jsonrpc":"2.0","id":"<sam-task>","result":{
  "kind":"status-update",
  "taskId":"<external-task>",
  "contextId":"<context>",
  "final":true,
  "status":{
    "state":"input-required",
    "message":{
      "role":"agent",
      "kind":"message",
      "parts":[{"kind":"text","text":"Approve this tool call?"}]
    }
  }
}}
```

## SAM 2.1.149 compatibility

The tested release preserves the A2A `contextId` on the user's follow-up, but creates a new SAM task and does not forward the interrupted downstream `taskId`.

This example therefore permits one pending approval per context and resumes it by `contextId`.

The product-quality solution is for the SAM external-agent gateway to persist and forward the downstream task ID as well as the context ID.

## Production hardening

The example stores pending approvals in memory and accepts simple text decisions. Production code should:

- use Redis or PostgreSQL;
- bind approval to user, tenant, conversation, tool, and exact arguments;
- use opaque signed approval IDs;
- enforce expiry;
- make duplicate decisions idempotent;
- re-authorize immediately before execution;
- audit proposal, decision, execution, and completion;
- use structured buttons/actions rather than substring matching.
