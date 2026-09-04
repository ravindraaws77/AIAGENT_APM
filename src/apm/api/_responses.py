"""Small helpers shared by apm.api.app and apm.api.tools_routes, so
neither module has to import from the other (both are wired into the
FastAPI app in apm.api.app's create_app).
"""

from __future__ import annotations

from fastapi import HTTPException

from apm.agent.graph import RunOutcome
from apm.api.schemas import RunOutcomeResponse


def upstream_error(exc: Exception) -> HTTPException:
    """Turn an unexpected failure from the graph/a tool (a network error,
    an exhausted retry, a reasoner parsing failure, ...) into a clean
    502 response with a readable message, instead of letting an
    unhandled 500 with a raw Python traceback reach the caller.
    Uvicorn still logs the full traceback server-side either way.
    """
    return HTTPException(status_code=502, detail=f"Upstream tool/agent error: {exc}")


def to_response(outcome: RunOutcome) -> RunOutcomeResponse:
    return RunOutcomeResponse(
        process_id=outcome.process_id,
        summary=outcome.summary,
        pending_action=outcome.pending_action,
        final_result=outcome.final_result,
    )
