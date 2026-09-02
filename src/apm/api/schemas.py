"""Pydantic request/response models for the FastAPI backend."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StartProcessRequest(BaseModel):
    """What to fetch when starting (or re-running) a process. At least
    one of gmail_query / calendar_query is required — the graph only
    calls a tool if a query for it is present (see apm.agent.graph's
    fetch_node).
    """

    gmail_query: str | None = None
    gmail_max_results: int = 5
    calendar_query: str | None = None
    calendar_max_results: int = 5


class DecisionRequest(BaseModel):
    approved: bool


class RunOutcomeResponse(BaseModel):
    """Mirrors apm.agent.graph.RunOutcome. Exactly one of pending_action /
    final_result is set: pending_action means the graph is paused waiting
    for a POST to /processes/{id}/decision; final_result means it's done.
    """

    process_id: str
    summary: str | None
    pending_action: dict[str, Any] | None
    final_result: dict[str, Any] | None
