"""FastAPI app: the HTTP surface over apm.agent.graph.

Run it with: uvicorn apm.api.app:app --reload --port 8000

Routes never call a tool's write/action method directly or bypass the
graph's approval interrupt — every mutation goes through /decision, which
calls resume_process, which is the only path to execute_node.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from apm.agent.graph import RunOutcome, resume_process, start_process
from apm.api.dependencies import get_graph, get_state_store
from apm.api.schemas import DecisionRequest, RunOutcomeResponse, StartProcessRequest
from apm.state.store import StateStore


def create_app() -> FastAPI:
    app = FastAPI(title="APM Agent API")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/processes")
    def list_processes(store: StateStore = Depends(get_state_store)) -> list[dict]:
        return store.list_processes()

    @app.get("/processes/{process_id}/status")
    def get_process_status(process_id: str, store: StateStore = Depends(get_state_store)) -> dict:
        status = store.get_status(process_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"unknown process_id: {process_id}")
        return status

    @app.get("/processes/{process_id}/history")
    def get_process_history(process_id: str, store: StateStore = Depends(get_state_store)) -> list[dict]:
        return store.list_events(process_id)

    @app.get("/processes/{process_id}/pending")
    def get_pending_actions(process_id: str, store: StateStore = Depends(get_state_store)) -> list[dict]:
        return store.list_pending_actions(process_id)

    @app.post("/processes/{process_id}/start", response_model=RunOutcomeResponse)
    def start(process_id: str, body: StartProcessRequest, graph=Depends(get_graph)) -> RunOutcomeResponse:
        queries: dict[str, dict] = {}
        if body.gmail_query is not None:
            queries["gmail"] = {"query": body.gmail_query, "max_results": body.gmail_max_results}
        if body.calendar_query is not None:
            queries["google_calendar"] = {"query": body.calendar_query, "max_results": body.calendar_max_results}
        if not queries:
            raise HTTPException(
                status_code=400, detail="at least one of gmail_query / calendar_query is required"
            )
        try:
            outcome = start_process(graph, process_id, queries)
        except Exception as exc:
            raise _upstream_error(exc) from exc
        return _to_response(outcome)

    @app.post("/processes/{process_id}/decision", response_model=RunOutcomeResponse)
    def decide(process_id: str, body: DecisionRequest, graph=Depends(get_graph)) -> RunOutcomeResponse:
        try:
            outcome = resume_process(graph, process_id, approved=body.approved)
        except Exception as exc:
            raise _upstream_error(exc) from exc
        return _to_response(outcome)

    return app


def _upstream_error(exc: Exception) -> HTTPException:
    """Turn an unexpected failure from the graph/a tool (a network error,
    an exhausted retry, a reasoner parsing failure, ...) into a clean
    502 response with a readable message, instead of letting an
    unhandled 500 with a raw Python traceback reach the caller.
    Uvicorn still logs the full traceback server-side either way.
    """
    return HTTPException(status_code=502, detail=f"Upstream tool/agent error: {exc}")


def _to_response(outcome: RunOutcome) -> RunOutcomeResponse:
    return RunOutcomeResponse(
        process_id=outcome.process_id,
        summary=outcome.summary,
        pending_action=outcome.pending_action,
        final_result=outcome.final_result,
    )


app = create_app()
