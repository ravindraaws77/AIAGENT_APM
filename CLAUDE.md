# CLAUDE.md

Guidance for Claude Code sessions working in this repository.

## What this project is

APM (Agentic Process Management) — see `README.md` and `docs/architecture.md`
for the full picture. This is a hackathon MVP for the TechIreland National AI
Challenge 2026, built incrementally as reviewed pull requests.

## Non-negotiable rule

**No tool call that writes, sends, or creates anything in a real external
system may execute without an explicit human approval step.** Read-only
calls are always fine. See `docs/security-guardrails.md`. When adding or
touching a tool connector, use the `tool-integration` skill in
`.claude/skills/`.

## Working conventions

- Each build phase is a separate branch + PR into `claude/hello-mt20cg` (see
  `docs/roadmap.md`). Don't combine phases into one PR, and don't start a
  later phase before the current one is merged.
- Never commit secrets. `.env.example` documents required variables;
  real values go in a local, gitignored `.env`.
- Every tool connector implements the common interface in
  `src/apm/tools/base.py` and is registered in `docs/capability-map.md`.
- Every action (read, proposed write, approval, rejection, execution,
  failure) is recorded via `src/apm/state/store.py`.
- Prefer dry-run-testable code: a connector should be exercisable with
  `dry_run=True` and no live credentials, so its logic can be reviewed and
  tested before anyone wires up real accounts.

## Layout

```
docs/            architecture, roadmap, capability map, api contract, security guardrails
.claude/skills/  best-practice skills for this repo (e.g. adding a tool)
src/apm/
  config.py      env/config loading
  state/         persistent status + audit log store
  tools/         one module per external tool, common interface in base.py
  agent/         LangGraph orchestration (phase 5+)
  ui/            Streamlit dashboard (phase 6+)
tests/           unit tests, runnable without live credentials
```
