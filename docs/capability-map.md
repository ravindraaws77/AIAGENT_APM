# Capability map — Workstream 2 (Agent Tools & Connectivity)

Deliverable per the team's workstream brief: *"Capability map by
system/tool, read/write/action possibilities, recommended connection
paths, known gaps/constraints/blockers."*

## Orchestration/automation platform comparison

Evaluated per the brief's mission ("explore OpenAI, Anthropic, and other
viable platforms; check connectors, plugins, MCPs, APIs, and available
tooling"):

| Platform | Type | Read/observe | Write/act | State + HITL approval | Verdict |
|---|---|---|---|---|---|
| **LangGraph** | Code framework (Python) | Yes, via any tool/MCP client | Yes, via any tool/MCP client | Native: checkpointer for persistent state, `interrupt()` / `Command(resume=...)` for human approval gates | **Chosen for the orchestration layer — implemented in phase 5** (`src/apm/agent/graph.py`). Matches the master architecture's Layer 4. Approval logic lives in reviewable code, not a visual canvas. One real gotcha found and fixed while implementing: code placed *before* an `interrupt()` call inside a node re-executes on resume, so side effects (like recording a pending action) must live in a separate, non-interrupting node — see the `propose_node`/`approval_node` split and its docstrings. |
| **MCP (Model Context Protocol)** | Connectivity standard | Yes | Yes | N/A (a transport/tooling standard, not an orchestrator) | **Chosen for the tool-connectivity layer** (Layer 5). Anthropic-originated, now an open standard; both our master architecture diagram and this workstream's own "suggested tools" call it out directly. |
| n8n (self-hosted, 2.0) | Low-code workflow platform | Yes, ~70 AI nodes incl. LangChain integration | Yes | Built-in persistent memory + HITL node patterns | Strong alternative; deepest AI-agent features among no-code tools and cheapest at volume (per-execution, not per-step pricing). Good candidate for a *later* notification/glue channel, not the core reasoning/approval brain for this challenge. |
| Make | Low-code workflow platform | Yes | Yes | Beta agent builder ("Maia") | Best visual-builder / cost balance of the no-code options; same "logic isn't in reviewable code" limitation as n8n for our purposes. |
| Zapier | SaaS automation, 8,000+ app connectors | Yes | Yes | Zapier Agents (higher-level, less configurable) | Widest connector catalog and the simplest non-technical setup; per-step task pricing is expensive at volume. Already available as an MCP-exposed connector in this environment — worth keeping in mind as a fast path for a connector we haven't built ourselves yet. |

**Decision:** LangGraph orchestrates; tools are exposed as MCP-style
connectors underneath it. No-code platforms are documented here as the
comparison this workstream asked for, not built into the MVP.

## Per-tool capability assessment

| Tool | Auth | Read/retrieve | Write/action | Recommended connection path | Known gaps / blockers |
|---|---|---|---|---|---|
| **Gmail** | Google OAuth 2.0 (user consent) | **Implemented (phase 2):** search/list threads, read message content and metadata — `src/apm/tools/gmail_tool.py` | **Implemented (phase 5):** send an email (`send_email`) — only ever called with `dry_run=False` from inside the agent graph's `execute_node`, after an approved `interrupt()`; draft/apply-labels remain unimplemented | Google API Python client (`google-api-python-client`) wrapped as a typed tool (`GmailTool`) with explicit capability flags; a `GmailClient` protocol lets tests substitute a fake client with no live credentials; can be re-exposed as an MCP server later without changing the tool interface | Sending is irreversible — always gated behind approval, never called with `dry_run=False` outside the graph. Needs a Google Cloud OAuth client (one-time setup, credentials never committed — see `.env.example`). Requests both `gmail.readonly` and `gmail.send` scopes (least-privilege beyond that: no broader Gmail scope requested). |
| **Google Calendar** | Google OAuth 2.0 (same consent screen as Gmail, can share scopes) | **Implemented (phase 3):** list/search events, read attendees/times/location — `src/apm/tools/calendar_tool.py` | **Implemented (phase 5):** create a single event (`create_event`) — same approval-gated pattern as Gmail's send; update-event/respond-to-invite remain unimplemented | Same Google API client library as Gmail (`GoogleApiCalendarClient`, same `google_auth.py` helper); a `CalendarClient` protocol lets tests substitute a fake client with no live credentials | Time zone / recurring-event handling adds complexity — out of scope for MVP (single, non-recurring events only). The Gmail/Calendar shared-token-cache issue is resolved: `apm.tools.google_auth.build_gmail_and_calendar_tools` requests both tools' scopes in one consent, used by the agent (`scripts/agent_demo.py`); the single-tool `build_gmail_tool`/`build_calendar_tool` factories still exist for the phase 2/3 demo scripts, which use one tool at a time. |
| **MS Excel** | Microsoft identity platform (Azure AD app registration), MSAL device-code flow, Microsoft Graph API | **Implemented (phase 4):** list worksheets, read a cell range — `src/apm/tools/excel_tool.py` | **Implemented (phase 5):** overwrite a cell range (`write_range`) — same approval-gated pattern as Gmail/Calendar; append-to-table remains unimplemented | Plain `requests` against the Graph REST API (`GraphApiExcelClient`), wrapped with the same tool interface as Gmail/Calendar; an `ExcelClient` protocol lets tests substitute a fake client with no live credentials | Needs a separate Azure AD app registration (different admin/consent flow than Google) — this is the reason Excel is its own phase rather than bundled with the Google tools. Workbook must already be on OneDrive/SharePoint (Graph API doesn't operate on local `.xlsx` files). Unlike Gmail/Calendar, the connector is bound to one specific workbook (drive item id) at construction time rather than operating on "the" mailbox/calendar — `scripts/excel_demo.py --list` helps find that id. Excel is not yet wired into `scripts/agent_demo.py` (Gmail + Calendar only) since it needs a workbook item id as an extra input; a natural phase 6 follow-up. |

## Common tool interface

Every connector implements the same shape (see `src/apm/tools/base.py`) so
the orchestration layer and the UI don't need tool-specific code:

- `capabilities`: which of `read`, `write`, `action` this tool supports
- `dry_run`: when true, a write/action call returns what *would* happen
  without doing it — used for local testing without live credentials
- every call is written to the audit log in `src/apm/state/store.py`,
  whether it was a read, a proposed write, an approval, a rejection, or an
  executed action
