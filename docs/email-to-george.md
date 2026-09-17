Subject: Re: HITL approval for tools on an external A2A agent

Hi George,

Yes, your use case is possible today, but it requires custom code in the external A2A agent.

We tested the same flow successfully with Solace Agent Mesh:

1. The model selects a tool that requires approval.
2. The external agent saves the proposed tool call but does not execute it.
3. It returns A2A `input-required`, which SAM displays in Chat.
4. The user replies Approve or Deny.
5. On approval, the external agent executes the saved call and resumes the model turn. On denial, it does not execute the tool.

The important distinction is that you cannot simply register SAM's internal HIL tools on an external A2A agent in the SAM version we tested. The external agent must implement the pause, pending-state storage, decision handling, execution gate, and model-resume logic itself. SAM provides the chat surface and carries the user's response.

There is one compatibility detail: SAM currently preserves the A2A `contextId` on the approval reply but does not forward the interrupted downstream `taskId`. The reference adapter therefore correlates one pending approval by `contextId`. This is suitable as an immediate solution; a production implementation should store approval state durably and use signed, expiring approval IDs.

Public reference implementation:

https://github.com/raphael-solace/sam-a2a-hil-approval

In short: yes, it is possible with custom code now; no, direct registration of SAM's native HIL tools on an external A2A agent is not currently the integration mechanism.

Best,
Raphael
