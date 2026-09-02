# Architecture — MVP mapping

This maps the bare-minimum build to the team's 5-layer master architecture
(`APM_ARCHITECTURE.PDF`) so it's obvious what's in scope now vs. later.

| # | Master layer | MVP status | MVP component |
|---|---|---|---|
| 1 | Experience / Presentation (avatar/UI) | Simplified | FastAPI backend (`src/apm/api/`, phase 6a) wrapping the agent, with a NiceGUI dashboard (`src/apm/ui/`, phase 6b) as the presentation layer — text/visual only, no avatar or voice yet |
| 2 | Real-Time Interaction (LiveKit + voice) | **Out of scope** | Deferred to a later phase once the core flow is proven |
| 3 | Intelligence / Conversation (reasoning model) | **Implemented (phase 5)** | `src/apm/agent/reasoner.py` — `ClaudeReasoner` calls Claude to summarize fetched data and propose at most one next action |
| 4 | Process Orchestration (LangGraph) | **Implemented (phase 5)** | `src/apm/agent/graph.py` — fetch → reason → propose → **human-approval `interrupt()`** → execute → persist. Try it end-to-end with `scripts/agent_demo.py` |
| 5 | Tools & Enterprise Systems | In scope | Gmail, Google Calendar, MS Excel connectors (`src/apm/tools/`, phases 2–4) |
| — | Security & Governance (cross-cutting) | In scope | No write/send/create action ever executes without an explicit human approval step. See `docs/security-guardrails.md`. |
| — | Memory & Persistence (cross-cutting) | In scope | `src/apm/state/store.py` — durable process status + audit log, phase 1 |
| — | Observability & Monitoring (cross-cutting) | Minimal | Every action attempt (proposed/approved/rejected/executed/failed) is written to the audit log in the state store |

## MVP end-to-end flow

```
 User opens dashboard
        │
        ▼
 Agent reads configured tools (Gmail / Calendar / Excel)
        │
        ▼
 Agent summarizes what it found, in plain language
        │
        ▼
 Agent proposes an action (e.g. "send a follow-up email",
 "create a reminder event", "log this row in the tracker")
        │
        ▼
 Graph pauses (interrupt) — action shown in the dashboard,
 nothing has happened yet
        │
        ├── Approve ──▶ tool executes the action ──▶ status + audit log updated
        │
        └── Reject ───▶ action discarded ──▶ status + audit log updated
```

The same pattern repeats for every tool and every proposed action: **read is
always allowed; write/send/create always stops for a human decision first.**

## Why LangGraph + MCP-style tool connectors

See `docs/capability-map.md` for the workstream-2 (Agent Tools &
Connectivity) comparison of LangGraph vs. n8n vs. Make vs. Zapier and the
per-tool read/write/action assessment.
