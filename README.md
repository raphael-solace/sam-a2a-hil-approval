# External A2A Tool Approval for Solace Agent Mesh

A minimal public reference showing **Approve or Reject before an external A2A agent executes a protected tool** while the conversation remains in Solace Agent Mesh Chat.

## The direct answer

> **This is possible today, but custom code is required in the external A2A agent.**

In the SAM version tested, you **cannot** register SAM's internal HIL tools on an external A2A agent and expect them to become callable tools in that agent's runtime.

The external agent must implement the approval state machine itself:

1. Intercept a protected model tool call before execution.
2. Persist the pending model turn and exact tool call.
3. Return A2A `input-required` to SAM.
4. Receive the user's Approve or Deny response from SAM Chat.
5. Execute only after approval.
6. Resume the original model turn with the matching `tool_result`.

SAM provides the conversation and approval surface. The external agent owns the tools, pending state, execution gate, and model resumption.

## What was verified

The reference flow was tested end-to-end against:

- Solace Agent Mesh chart `2.1.149`
- SAM application `2.346.0`
- A2A protocol `0.3`

### Approve

1. User asks the agent to list `/`.
2. The LLM requests `list_directory({"path":"/"})`.
3. The external agent returns `input-required`; the tool has not run.
4. User replies `yes, approve`.
5. The tool runs and the result is returned to the LLM.
6. The external task completes.

### Deny

1. The same protected tool is proposed.
2. User replies `deny`.
3. The tool does not run.
4. The model acknowledges the denial and the task completes.

## Why an approval-aware agent is necessary

An agent that knows approval is required but cannot ask for approval or resume the original tool call has only one safe option: refuse execution.

The custom code in [`src/app.py`](src/app.py) adds the missing behavior. It does not bypass the policy—it turns the policy into a usable pause/approve/resume workflow.

## Architecture

```text
User in SAM Chat
       |
       v
SAM external-agent proxy
       |
       v
External A2A agent
  1. LLM proposes tool_use
  2. Agent saves tool call
  3. Agent returns input-required
       |
       v
User approves or denies in SAM Chat
       |
       v
External A2A agent
  4. Correlates pending request
  5. Executes only if approved
  6. Sends tool_result to LLM
  7. Returns completed
```

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY='...'
export ANTHROPIC_MODEL='claude-opus-5'
uvicorn src.app:app --host 0.0.0.0 --port 8080
```

Or use another Anthropic-compatible endpoint:

```bash
export ANTHROPIC_BASE_URL='https://your-proxy.example.com'
export ANTHROPIC_AUTH_TOKEN='...'
```

Never commit credentials.

## Register in SAM

Expose the service at a URL reachable by SAM, then connect it as an external agent:

- Agent URL: `https://your-agent.example.com/`
- Agent card URL: `https://your-agent.example.com/.well-known/agent-card.json`
- Agent card location: `well_known`
- Request timeout: at least `600` seconds for interactive approval

The agent card advertises the agent and its skills. It does **not** register SAM's native tools into this service.

## Compatibility note

In the SAM release tested, the approval follow-up preserved the A2A `contextId`, but SAM created a new task and did not forward the interrupted downstream `taskId`.

This example therefore resumes one pending approval by `contextId`.

For production, the SAM external-agent gateway should persist and forward the downstream task ID, and the agent should store approval state durably. See [docs/protocol.md](docs/protocol.md).

## Production warning

This repository is an integration example, not a production authorization service. Before production use:

- replace in-memory state with Redis/PostgreSQL;
- bind approval to user, tenant, conversation, tool, and exact arguments;
- use signed, expiring, single-use approval IDs;
- re-authorize at execution time;
- handle duplicate delivery idempotently;
- audit proposal, decision, execution, and completion;
- replace free-text matching with structured approval actions.

## Repository contents

- [`src/app.py`](src/app.py) — complete A2A approval adapter
- [`docs/protocol.md`](docs/protocol.md) — protocol behavior and production guidance
- [`docs/email-to-george.md`](docs/email-to-george.md) — concise send-ready answer
- [`deploy/kubernetes.yaml`](deploy/kubernetes.yaml) — environment-neutral Kubernetes example
- [`tests/test_state_machine.py`](tests/test_state_machine.py) — approval and denial state tests

## License

MIT
