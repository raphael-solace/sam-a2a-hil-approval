# Verification Record

Last run: 2026-09-18

## Scope

The exact source in this public repository was tested at three levels:

1. deterministic state-machine and HTTP tests;
2. a locally launched FastAPI service calling a real Claude model through the configured Anthropic-compatible endpoint;
3. the same source built as a `linux/amd64` container, deployed behind a live Solace Agent Mesh external-agent registration, and driven through SAM Chat.

## Automated tests

```bash
pytest -q tests
```

Result:

```text
5 passed
```

The tests assert:

- the executor is called zero times when a protected call is first proposed;
- ambiguous input keeps the task in `input-required`;
- approval executes the exact saved tool once;
- denial never calls the executor;
- `don't approve` is classified as denial, not approval;
- streaming returns a submitted Task followed by a final `input-required` status update;
- pending state is cleared after approval and denial.

## Real-model local service

The exact app was launched with Uvicorn and a real Claude model. One initial full cycle passed, then five consecutive full cycles passed after hardening decision parsing.

Each cycle verified:

```text
submitted -> input-required
approve -> completed
reject -> completed
pending approvals after test -> 0
```

The model selected:

```text
list_directory({"path":"/"})
```

Approval returned actual directory entries. Denial stated that execution was rejected and returned no directory contents.

A concurrent health test issued health requests while the model call was in flight:

```text
health checks: 35
maximum latency: 41.6 ms
task state: input-required
```

This confirms that running the synchronous model SDK call through `asyncio.to_thread` keeps FastAPI's health endpoint responsive.

## Live Solace Agent Mesh test

The exact public source was built as image `a2a-hil-approval:1.0.1` for `linux/amd64` and deployed to the test SAM environment. The SHA-256 of `/app/app.py` inside the running pod matched the public checkout exactly: `aa6f90423dbfb058536887e78c0bd3892e9b5a8e0a65b17f95d0f28dfc50eadc`.

Observed pod state:

```text
READY: true
RESTARTS: 0
MODEL: claude-opus-4-8
PENDING: 0
```

### Live approval

1. Opened a new SAM Chat with the HIL agent.
2. Asked it to list `/`.
3. Confirmed the UI displayed the proposed `list_directory({"path":"/"})` call before execution.
4. Replied `yes, approve`.
5. Confirmed the UI stated that approval was received, the tool ran successfully, and actual root entries were returned.

### Live denial and negation safety

1. Opened another new SAM Chat.
2. Asked it to list `/`.
3. Replied `don't approve` rather than the simpler `deny`.
4. Confirmed the UI reported `Approval denied`, explicitly stated that the tool did not run, and returned no directory contents.

This negation test guards against the unsafe substring behavior where the word `approve` inside `don't approve` might otherwise be mistaken for approval.

## Sustained health

Ten consecutive public checks returned:

```text
platform=healthy
hil=running
```

## Compatibility issue found and resolved

The current Anthropic API supports strict tool schemas, but the SAP AI Core compatibility proxy used by the live SAM environment rejected the `strict` field. The public example retains `additionalProperties: false` and omits the unsupported `strict` field so it works through that tested proxy.

## Known external environment issue

The live environment's outer nginx proxy has a small request-body limit. Some SAM WebUI task-history save requests return HTTP 413 after the chat response is already complete. This is separate from the external A2A approval adapter: approve and deny both completed correctly, the agent remained running, and pending state returned to zero.

The proxy limit should still be raised for clean WebUI persistence. It does not alter the test conclusion for the HIL execution gate.

## Confidence statement

The reference implementation is verified for the demonstrated single-pending-approval-per-context pattern on SAM 2.1.149. Its approve/reject execution gate works with the tested proxy and SAM Chat flow. It is not represented as a production authorization service. Production use still requires durable pending state, structured signed decisions, identity binding, expiry, idempotency, execution-time authorization, and audit logging.
