"""API-key auth for the /tools/* surface.

docs/api-contract.md used to document this as a known, unfilled gap
("No auth today ... adding an API key/bearer check ... is a known,
separate piece of work, not yet done"). This is that piece of work.

Enforcement is opt-in via APM_TOOLS_API_KEY, same "env var present ->
behavior changes" convention as every other optional piece of config in
apm.config (Excel's workbook path, the Google/MS Graph credentials):
leaving it unset keeps every existing test, demo script, and local run
working exactly as before (no header required); setting it is what
turns this on for a deployment reachable over a network boundary that
isn't already trusted, per CLAUDE.md's "adding or touching a tool
connector" guidance and docs/security-guardrails.md.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from apm.config import load_settings


def require_tools_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    settings = load_settings()
    if settings.tools_api_key is None:
        return
    if x_api_key != settings.tools_api_key:
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")
