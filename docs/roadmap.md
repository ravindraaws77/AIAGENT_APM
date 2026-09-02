# Roadmap — PR sequence

Each phase is its own branch and pull request into `claude/hello-mt20cg`.
Nothing merges without review; nothing in a later phase starts until the
current one is approved.

| Phase | Branch | What it adds | Needs live credentials? |
|---|---|---|---|
| 1 | `claude/apm-01-scaffold` | Project structure, docs, persistent state/audit store, common tool interface, best-practices skill | No |
| 2 | `claude/apm-02-gmail` | Gmail connector — read/search only. Send is deferred to phase 5, where the approval-interrupt gate exists | Yes (Google OAuth) to run for real via `scripts/gmail_demo.py`; fully unit-tested with a fake client without it |
| 3 | `claude/apm-03-calendar` | Google Calendar connector — list/search only, same read-first pattern as Gmail | Yes (Google OAuth) to run for real via `scripts/calendar_demo.py`; fully unit-tested with a fake client without it |
| 4 | `claude/apm-04-excel` | MS Excel (Microsoft Graph) connector — list worksheets, read ranges only | Yes (Azure AD app registration) to run for real via `scripts/excel_demo.py`; fully unit-tested with a fake client without it |
| 5 | `claude/apm-05-agent` | LangGraph graph: fetch → summarize → propose → **human-approval interrupt** → execute → persist (`src/apm/agent/graph.py`, `src/apm/agent/reasoner.py`). Adds the write/action methods deferred earlier: Gmail `send_email`, Calendar `create_event`, Excel `write_range` — each only reachable from `execute_node`, after an approved interrupt. `scripts/agent_demo.py` runs the full flow with Gmail + Calendar (Excel needs a workbook item id as extra input — not yet wired into the demo) | Yes (Anthropic API key + Google OAuth) to run for real; the full control flow (including the interrupt/resume approval gate) is unit-tested with fake tools and a fake reasoner without it |
| 6 | `claude/apm-06-ui` | Streamlit dashboard: tool status, fetched data, pending approvals with Approve/Reject, history | Same as phase 5 |

## Beyond phase 6 (not started — future phases, for discussion)

- Voice/avatar layer (LiveKit) — Layers 1–2 of the master architecture
- More tools (Jira, ERP/CRM, databases) per the workstream's capability-map pattern
- Multi-process support (today's MVP assumes one process/case at a time)
- Production-grade persistence (swap the JSON store for Postgres) and real auth/RBAC for the dashboard itself
