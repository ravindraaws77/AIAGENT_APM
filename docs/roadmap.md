# Roadmap — PR sequence

Each phase is its own branch and pull request into `claude/hello-mt20cg`.
Nothing merges without review; nothing in a later phase starts until the
current one is approved.

| Phase | Branch | What it adds | Needs live credentials? |
|---|---|---|---|
| 1 | `claude/apm-01-scaffold` | Project structure, docs, persistent state/audit store, common tool interface, best-practices skill | No |
| 2 | `claude/apm-02-gmail` | Gmail connector — read/search only. Send is deferred to phase 5, where the approval-interrupt gate exists | Yes (Google OAuth) to run for real via `scripts/gmail_demo.py`; fully unit-tested with a fake client without it |
| 3 | `claude/apm-03-calendar` | Google Calendar connector — list/search only, same read-first pattern as Gmail | Yes (shares Google OAuth from phase 2) |
| 4 | `claude/apm-04-excel` | MS Excel (Microsoft Graph) connector — read ranges/tables only | Yes (Azure AD app registration) |
| 5 | `claude/apm-05-agent` | LangGraph graph: fetch → summarize → propose → **human-approval interrupt** → execute → persist. Also adds the write/action methods (Gmail send, Calendar create/update, Excel write) now that the interrupt gate exists to sit in front of them | Yes (Anthropic API key for the reasoning model) |
| 6 | `claude/apm-06-ui` | Streamlit dashboard: tool status, fetched data, pending approvals with Approve/Reject, history | Same as phase 5 |

## Beyond phase 6 (not started — future phases, for discussion)

- Voice/avatar layer (LiveKit) — Layers 1–2 of the master architecture
- More tools (Jira, ERP/CRM, databases) per the workstream's capability-map pattern
- Multi-process support (today's MVP assumes one process/case at a time)
- Production-grade persistence (swap the JSON store for Postgres) and real auth/RBAC for the dashboard itself
