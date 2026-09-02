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
| **LangGraph** | Code framework (Python) | Yes, via any tool/MCP client | Yes, via any tool/MCP client | Native: checkpointer for persistent state, `interrupt()` / `Command(resume=...)` for human approval gates | **Chosen for the orchestration layer.** Matches the master architecture's Layer 4. Approval logic lives in reviewable code, not a visual canvas. |
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
| **Gmail** | Google OAuth 2.0 (user consent) | **Implemented (phase 2):** search/list threads, read message content and metadata — `src/apm/tools/gmail_tool.py` | Create draft, send message, apply labels — **not yet implemented.** Deferred to phase 5, where the LangGraph human-approval `interrupt()` exists, so a send call is never reachable without it (per the tool-integration skill's read-first rule) | Google API Python client (`google-api-python-client`) wrapped as a typed tool (`GmailTool`) with explicit capability flags; a `GmailClient` protocol lets tests substitute a fake client with no live credentials; can be re-exposed as an MCP server later without changing the tool interface | Sending is irreversible — will be gated behind approval always once added. Needs a Google Cloud OAuth client (one-time setup, credentials never committed — see `.env.example`). Read-only scope (`gmail.readonly`) requested for now, matching least-privilege guidance. |
| **Google Calendar** | Google OAuth 2.0 (same consent screen as Gmail, can share scopes) | List/search events, read attendees/times | Create event, update event, respond to invite | Same Google API client library as Gmail; one shared OAuth flow can cover both scopes | Time zone / recurring-event handling adds complexity — out of scope for MVP (single, non-recurring events only). |
| **MS Excel** | Microsoft identity platform (Azure AD app registration) + Microsoft Graph API | Read worksheet ranges/tables from a OneDrive/SharePoint-hosted workbook | Write/update cell ranges, append table rows | Microsoft Graph SDK or plain `requests` against the Graph REST API, wrapped with the same tool interface as Gmail/Calendar | Needs a separate Azure AD app registration (different admin/consent flow than Google) — this is the reason Excel is its own phase rather than bundled with the Google tools. Workbook must be on OneDrive/SharePoint (Graph API doesn't operate on local `.xlsx` files). |

## Common tool interface

Every connector implements the same shape (see `src/apm/tools/base.py`) so
the orchestration layer and the UI don't need tool-specific code:

- `capabilities`: which of `read`, `write`, `action` this tool supports
- `dry_run`: when true, a write/action call returns what *would* happen
  without doing it — used for local testing without live credentials
- every call is written to the audit log in `src/apm/state/store.py`,
  whether it was a read, a proposed write, an approval, a rejection, or an
  executed action
