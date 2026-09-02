# Security, guardrails & trust — MVP baseline

Scoped from `security_guardrails_trust_overview.pdf` (Workstream 5) to what
this MVP actually implements. This is a starting baseline, not the full
target state.

## 1. Access & permissions
- Every tool connector declares its own OAuth scopes explicitly; request
  the minimum scope needed (e.g. `gmail.readonly` before `gmail.send`).
- Credentials are per-user (your own Google/Microsoft account), never a
  shared service account, for this MVP.

## 2. Credential & secret management
- Secrets live only in a local `.env` file (or your OS keychain/OAuth token
  cache) — never in code, never committed. `.env.example` documents the
  required variable names with no real values.
- `.gitignore` blocks `.env`, `*token*.json`, `credentials.json`, and
  `client_secret*.json` by pattern, as a backstop against accidental commits.

## 3. Data protection
- No email/calendar/spreadsheet content is persisted beyond what's needed
  to show the current process status — the state store keeps summaries and
  action records, not full raw payloads, wherever practical.

## 4. Auditability & traceability
- Every tool call (read or write) and every approval decision is appended
  to the audit log in `src/apm/state/store.py`: who/what proposed it, what
  it was, the decision, and the outcome. Logs are append-only from the
  application's perspective.

## 5. The core guardrail: human approval before any write/send/action

**This is the non-negotiable rule for the whole MVP:** a tool's `read`
capability can run whenever the agent needs it. A tool's `write` or
`action` capability can **only** run after an explicit human decision
(Approve, via the UI). There is no code path in phases 2–6 that sends an
email, creates a calendar event, or writes a spreadsheet row without that
step. This is implemented, not aspirational: `src/apm/agent/graph.py`'s
`execute_node` is the only place any tool's write/action method is ever
called with `dry_run=False`, and it only runs after `approval_node`'s
`interrupt()` has returned an approved decision — the graph physically
pauses and checkpoints state at that point, it isn't a soft "best effort"
check, execution cannot continue without a `Command(resume=...)` signal.

Every connector also supports a `dry_run` mode: report exactly what a
write/action call *would* do without doing it, used for local testing
before real credentials are wired up.

**Human approval is necessary but not sufficient on its own** — found in
practice, not just in theory: with a self-sent test email that had no
real customer address anywhere in it, the reasoner proposed sending to a
fabricated `customer@example.com`, and a human approver had no way to
recognize that address as fake at a glance rather than a real domain
they simply didn't recognize. Two fixes, at two different layers:
- The reasoner's prompt now explicitly forbids inventing contact details
  not present in the fetched data (`apm/agent/reasoner.py`'s
  `SYSTEM_PROMPT`) — a mitigation, not a guarantee.
- `GmailTool.send_email` hard-refuses any RFC 2606 reserved/placeholder
  domain (`example.com`, anything under `.test`/`.example`/`.invalid`/
  `.localhost`, etc.) regardless of `dry_run` or approval status — a
  guarantee, since it doesn't depend on the model following instructions.

## 6. Least privilege in practice for this MVP
- Start every new tool integration read-only; add write/action scopes only
  once the read path is reviewed and working (matches the workstream's own
  phase ordering: "Not yet ... first discover what already exists").
- Production/live-account use always goes through the approval UI — there
  is intentionally no "autonomous mode" flag in this MVP.
