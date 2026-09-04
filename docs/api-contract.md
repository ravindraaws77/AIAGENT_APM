# Integration layer API contract — `/tools/*`

This is the stable contract for the connector/enterprise-systems layer
(`src/apm/tools`, exposed over HTTP by `src/apm/api/tools_routes.py`).
It's written for whatever consumes it — a specialized agent, a
supervisor/orchestrator, a script — not for a customer or the outside
world: this API is internal to the APM app. A reasoning/orchestration
layer is assumed to sit in front of it and is out of scope here; this
doc only covers the boundary between "something wants to read or act on
a real system" and the connectors that actually do it.

For the Python-level connector contract (how to add or change a
connector, `dry_run`, capability flags) see
`.claude/skills/tool-integration/SKILL.md` and `src/apm/tools/base.py`.
For per-tool auth/setup/known gaps, see `docs/capability-map.md`. This
doc is the HTTP surface only.

## Two separate APIs — don't mix them up

`src/apm/api/app.py` also exposes a *reasoning-driven* flow (`/query`,
`/processes/{id}/start`, `/processes/{id}/decision`) where this repo's
own `ClaudeReasoner` decides what to summarize and propose. That flow
is not this contract, needs `ANTHROPIC_API_KEY`, and is not the
integration point for an external reasoning/agent layer. Everything
below is `/tools/*` — no reasoning, no Anthropic dependency, just the
connectors plus the approval gate.

## Base URL

Wherever `uvicorn apm.api.app:app` is running, e.g. `http://127.0.0.1:8000`
locally. See `docs/running-locally.md` for how to start it (`pip install
-e ".[integration-layer]"` is enough — no `[ui]` needed for this API).

## Conventions that hold for every route below

- **`process_id` is required on every call** (read or write) — it's the
  audit-trail key (`StateStore.log_event`), not a resource id you look
  up first. Reuse the same `process_id` across a whole business
  process/case so its history reads as one thread.
- **Reads execute immediately** and return the tool's data directly, no
  approval step — this mirrors `docs/architecture.md`'s rule: *read is
  always allowed*.
- **Writes never execute immediately.** Every write route returns a
  `RunOutcomeResponse` with `pending_action` set and `final_result:
  null` — the action is recorded but not run. Nothing happens in the
  real system until a human decision arrives via the matching decision
  route. This is CLAUDE.md's non-negotiable rule, enforced at the
  connector layer (`BaseTool.require_dry_run_guard`) as well as here —
  there is no flag or parameter anywhere in this API that skips it.
- **Errors:**
  - `503` — the tool isn't configured on this server (e.g. no
    `APM_EXCEL_WORKBOOK_PATH` set). Returned before anything is
    recorded — a write call that 503s creates no pending action.
  - `502` — the tool call itself failed (a network error, an exhausted
    retry, an upstream API error). `detail` carries a readable message;
    the server logs the full traceback.
  - `422` — the request body didn't match the schema (standard FastAPI
    validation).
- **Auth.** Every `/tools/*` route requires a matching `X-API-Key`
  header once `APM_TOOLS_API_KEY` is set on the server
  (`apm.api.auth.require_tools_api_key`) — a mismatched or missing key
  returns `401`. Left unset, the API stays open (no header required),
  which is fine for local dev/tests but not once this crosses any
  network boundary that isn't already trusted — see
  `docs/security-guardrails.md`.

## Gmail

| Route | Kind | Request body | Returns |
|---|---|---|---|
| `POST /tools/gmail/search` | read | `{process_id, query, max_results?: 10}` | `[{message_id, thread_id, sender, subject, snippet, received_at}, ...]` |
| `POST /tools/gmail/read` | read | `{process_id, message_id}` | `{message_id, thread_id, sender, subject, snippet, received_at}` |
| `POST /tools/gmail/send` | **write** | `{process_id, to, subject, body}` | `RunOutcomeResponse` (see below) |

`query` uses Gmail's search syntax (e.g. `"from:customer@example.com
newer_than:14d"`). `send` refuses outright — even after approval — if
`to` is an RFC 2606 reserved/placeholder domain (`example.com` and
similar); see `gmail_tool.py`'s `RESERVED_PLACEHOLDER_DOMAINS`.

## Google Calendar

| Route | Kind | Request body | Returns |
|---|---|---|---|
| `POST /tools/calendar/search` | read | `{process_id, query?, time_min?, time_max?, max_results?: 10}` | `[{event_id, title, start, end, attendees, location}, ...]` |
| `POST /tools/calendar/read` | read | `{process_id, event_id}` | `{event_id, title, start, end, attendees, location}` |
| `POST /tools/calendar/create-event` | **write** | `{process_id, title, start, end, attendees?, location?}` | `RunOutcomeResponse` |

`start`/`end` are RFC3339 datetimes (e.g. `"2026-09-10T15:00:00Z"`).
Only single, non-recurring events — no recurrence support.

## Excel (local file or Google Drive `.xlsx`)

| Route | Kind | Request body | Returns |
|---|---|---|---|
| `POST /tools/excel/worksheets` | read | `{process_id}` | `["Sheet1", "Renewals", ...]` |
| `POST /tools/excel/read` | read | `{process_id, sheet_name?, address?}` | `{sheet_name, address, values: [[...], ...]}` |
| `POST /tools/excel/write` | **write** | `{process_id, sheet_name, address, values: [[...], ...]}` | `RunOutcomeResponse` |

One workbook per running server (`APM_EXCEL_WORKBOOK_PATH` or
`APM_EXCEL_DRIVE_FILE_ID` — see `docs/capability-map.md`); if neither
is set, every Excel route 503s. `read`'s `sheet_name`/`address` default
to the workbook's first worksheet and its whole used range when
omitted — pass them explicitly for anything more specific.

## Approving or rejecting a write

Every write route above returns a paused `RunOutcomeResponse`:

```json
{
  "process_id": "order-4521",
  "summary": null,
  "pending_action": {
    "type": "approval_request",
    "action_id": "…",
    "tool": "gmail",
    "method": "send_email",
    "description": "Send email to customer@realcorp.io: 'Update'",
    "payload": {"to": "customer@realcorp.io", "subject": "Update", "body": "…"},
    "category": "manual"
  },
  "final_result": null
}
```

Resolve it with:

```
POST /tools/actions/{process_id}/decision
{"approved": true}
```

This is a **different route from `/processes/{id}/decision`** (which
belongs to the reasoning flow above) — a process id started via a
`/tools/*` write must be resolved via `/tools/actions/{id}/decision`,
never the other one; they're backed by separate LangGraph checkpointers
(`apm.api.dependencies.get_action_graph` vs. `get_graph`) and mixing
them fails with an unknown-thread-id error rather than silently doing
the wrong thing.

On approval, the response's `final_result` is set (`pending_action:
null`):

```json
{
  "process_id": "order-4521",
  "summary": null,
  "pending_action": null,
  "final_result": {
    "executed": true,
    "description": "Send email to customer@realcorp.io: 'Update'",
    "details": {"to": "customer@realcorp.io", "subject": "Update", "message_id": "…"}
  }
}
```

On rejection: `final_result: {"executed": false, "reason": "rejected"}`
— nothing was sent/created/written.

## Worked example (Gmail send)

```
POST /tools/gmail/search
{"process_id": "order-4521", "query": "newer_than:14d order 4521"}
→ 200, list of matching emails

POST /tools/gmail/send
{"process_id": "order-4521", "to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."}
→ 200, pending_action set — nothing sent yet

...human approves...

POST /tools/actions/order-4521/decision
{"approved": true}
→ 200, final_result.executed == true — now it's actually sent
```

`GET /processes/{process_id}/history` and `GET
/processes/{process_id}/pending` (both already existed, unchanged by
this doc) work the same for a `/tools/*`-driven process id as for a
reasoning-flow one — the audit trail and pending-action store are
shared infrastructure (`src/apm/state/store.py`), not specific to
either API.

## Stability

Treat this as the contract a specialized agent codes against: request/
response shapes here (`src/apm/api/schemas.py`) shouldn't change
casually. Adding a new tool or a new read/write method is additive and
safe; changing an existing route's request/response shape is a breaking
change for anything already built against it.
