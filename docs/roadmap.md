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
| 6a | `claude/apm-06a-api` | FastAPI backend wrapping the agent: start a process, list/fetch status and history, submit an Approve/Reject decision. Dependency-injected so it's testable with fake tools/reasoner, same as the graph itself | Same as phase 5 to run for real; fully testable with FastAPI's TestClient + fakes without it |
| 6b | `claude/apm-06b-frontend` | NiceGUI dashboard (`src/apm/ui/app.py`), calling the 6a API over HTTP — never imports the agent/tools directly: API connectivity status, a form to start a process (Gmail/Calendar queries), the plain-language summary, a pending-approval card with Approve/Reject buttons, and a history table. Pure request/response logic lives in `src/apm/ui/logic.py`, unit-tested without a browser | The 6a API running (`uvicorn apm.api.app:app --port 8000`), then `python -m apm.ui.app` |

**This completes the bare-minimum end-to-end MVP**: a person can open the dashboard, fetch real Gmail/Calendar data for a process, see Claude's plain-language summary and proposed next action, approve or reject it, and see the result — all with status/audit persisted for later. Excel is built (phase 4) but not yet wired into the agent/API/UI (needs a workbook item id as extra input) — a natural phase 7 candidate.

**Post-MVP hardening, found by real testing (not separately numbered phases, each its own PR):** a reasoner JSON-parsing crash on a markdown-fenced response; the reasoner fabricating a placeholder recipient when no real one was in the fetched data (now hard-refused at the tool layer, RFC 2606 reserved domains); no retry on a transient network error during a read, and a raw 500 instead of a clean API error; the approval card showing a raw payload dict instead of labeled fields; and — directly serving the "recognise when something has stalled" / "continuous learning from outcomes" goals in the original concept doc — the reasoner now classifies each situation with a stable category slug (e.g. `shipment_delay`), color-coded consistently in both the approval card and the History table, so a recurring pattern across different processes (three orders delayed by the same supplier issue, say) is visually obvious rather than three unrelated-looking approvals.

| 7a | `claude/apm-07a-intent` | Free-text intent parsing: `ClaudeIntentParser` (`src/apm/agent/intent.py`), same protocol-based pattern as the reasoner, turns a plain-language request ("chase up order 4521", "check the Acme renewal") into a process id + Gmail/Calendar queries. New `POST /query` endpoint runs it straight through the existing graph, reusing known process ids from the state store so a follow-up request continues the same order instead of minting a new one. No UI change yet — the dashboard still uses the phase 6b form/`/start`. | Yes (Anthropic API key) to run for real; fully unit-tested with a fake parser without it |

## Beyond phase 7a (not started — future phases, for discussion)

- **7b** — NiceGUI rework: replace the process-id/Gmail-query/Calendar-query form with a single free-text prompt bar wired to `POST /query`, plus an orders list (from `GET /processes`) and a per-order detail page (`/orders/{process_id}`) instead of today's single flat page
- Voice/avatar layer (LiveKit) — Layers 1–2 of the master architecture
- More tools (Jira, ERP/CRM, databases) per the workstream's capability-map pattern
- Cross-process search (one free-text query surfacing multiple matching orders, not just resolving to one)
- Production-grade persistence (swap the JSON store for Postgres) and real auth/RBAC for the dashboard itself
