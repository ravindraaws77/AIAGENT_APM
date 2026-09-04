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


class QueryRequest(BaseModel):
    """A free-text request ("chase up order 4521", "check the Acme
    renewal"), routed through apm.agent.intent to resolve a process id and
    Gmail/Calendar queries before running the same graph /start uses.
    """

    text: str


class RunOutcomeResponse(BaseModel):
    """Mirrors apm.agent.graph.RunOutcome. Exactly one of pending_action /
    final_result is set: pending_action means the graph is paused waiting
    for a decision (POST /processes/{id}/decision for the reasoning
    flow, POST /tools/actions/{id}/decision for a /tools/* write);
    final_result means it's done.
    """

    process_id: str
    summary: str | None
    pending_action: dict[str, Any] | None
    final_result: dict[str, Any] | None


# -- /tools/* request models ---------------------------------------------
# Thin request shapes for the direct per-tool read/write routes
# (apm.api.tools_routes) -- one field per keyword argument the matching
# apm.tools method takes, plus process_id (every tool method needs one,
# for the audit trail). No reasoning here: a caller supplies exactly the
# read it wants, or the write it wants proposed.


class GmailSearchRequest(BaseModel):
    process_id: str
    query: str
    max_results: int = 10


class GmailReadRequest(BaseModel):
    process_id: str
    message_id: str


class GmailSendRequest(BaseModel):
    process_id: str
    to: str
    subject: str
    body: str


class CalendarSearchRequest(BaseModel):
    process_id: str
    query: str | None = None
    time_min: str | None = None
    time_max: str | None = None
    max_results: int = 10


class CalendarReadRequest(BaseModel):
    process_id: str
    event_id: str


class CalendarCreateEventRequest(BaseModel):
    process_id: str
    title: str
    start: str
    end: str
    attendees: list[str] | None = None
    location: str | None = None


class ExcelWorksheetsRequest(BaseModel):
    process_id: str


class ExcelReadRequest(BaseModel):
    process_id: str
    sheet_name: str | None = None
    address: str | None = None


class ExcelWriteRequest(BaseModel):
    process_id: str
    sheet_name: str
    address: str
    values: list[list[Any]]
