---
name: reset-demo-data
description: Use when the user wants to reset, clean up, or start over with the APM demo environment — clearing local process/history state, optionally cached OAuth tokens, and the Gmail/Calendar data scripts/seed_demo_data.py created. Invoke before re-running a demo from a clean slate, or when stale orders/approvals from earlier testing are cluttering the dashboard.
---

# Resetting the APM demo environment

This repo's local state (`state/` — every process, its history, and any
pending approvals) persists across restarts by design, so it survives
between demo runs. That's the right default, but it means stale data
from earlier testing sticks around until something clears it — this is
that something.

## What gets cleared, and how

| What | Where it lives | Cleared by |
|---|---|---|
| Process status, history, pending approvals | `state/` (local JSON, gitignored) | `scripts/reset_demo_data.py` (automatic) |
| Cached OAuth tokens | `.google_token.json`, `.ms_graph_token_cache.json` | `scripts/reset_demo_data.py --tokens` (opt-in — only if you want to force fresh sign-in) |
| Seeded Gmail messages / Calendar events | The real sandbox Google account | **Manual** — no delete capability is built into the tool connectors (see `docs/capability-map.md`); this is a deliberate scope limit, not an oversight |

## Steps

1. **Stop the running API and UI processes first** (`Ctrl+C` in both terminals). The backend holds process state in memory (the LangGraph checkpointer) independent of the state file — restarting after cleanup is what actually gives a clean slate, not the file deletion alone.

2. **Run the reset script:**
   ```
   python scripts/reset_demo_data.py
   ```
   It asks for confirmation that the servers are stopped, then deletes `state/`. Options:
   - `--tokens` — also clear cached OAuth tokens (only needed to force a fresh Google/Microsoft sign-in, e.g. switching accounts)
   - `--reseed <contact-email>` — immediately re-run `scripts/seed_demo_data.py` afterward with the given contact email
   - `--yes` — skip the confirmation prompt (only if you've already confirmed the servers are stopped yourself)

3. **Manually clean up the real Gmail/Calendar seed data** — the script prints the exact search query and event titles to remove:
   - Gmail: search `subject:("Order #401" OR "Order #402" OR "Order #403" OR "Order #404" OR "Order #405" OR "Order #406")`, select all, delete. Also search for any order numbers used in ad hoc manual testing, and any "Mail Delivery Subsystem" bounce notifications.
   - Calendar: delete "Renewal call - Acme Corp" and "Contract review - Globex" (and anything else approved into the calendar during testing).

4. **Restart the API and UI**, and re-seed if you skipped `--reseed` in step 2:
   ```
   uvicorn apm.api.app:app --reload --port 8000
   python -m apm.ui.app
   python scripts/seed_demo_data.py <contact-email>
   ```

## Why there's no automated Gmail/Calendar cleanup

Building a `delete_message`/`delete_event` capability would mean a new write/action method on `GmailTool`/`CalendarTool` — per the `tool-integration` skill, that needs the same read-first, dry-run, approval-gated treatment as every other write capability in this repo, not a quick add-on to a cleanup script. If deleting seed data becomes a frequent need, that's a legitimate future connector capability to propose separately — not something to bolt on here without going through that same discipline.
