"""Pure, framework-free helpers for the NiceGUI dashboard (app.py).

Kept separate from app.py — the actual NiceGUI page wiring — so this
logic is unit-testable without a browser, NiceGUI's test harness, or a
running API server. Mirrors the rest of the repo's pattern of separating
protocol/pure-logic from real I/O (e.g. the tool connectors' *Client
protocols vs. their real API-backed implementations).
"""

from __future__ import annotations

from typing import Any


def build_start_request(gmail_query: str, calendar_query: str) -> dict[str, str]:
    """Build the POST /processes/{id}/start request body from the two
    query inputs, omitting empty ones. Returns {} if neither is set — the
    caller should treat that as "nothing to fetch" and not call the API
    (the backend would reject it with a 400 anyway; checking here avoids
    a round trip for an input mistake the UI can catch immediately).
    """
    body: dict[str, str] = {}
    if gmail_query.strip():
        body["gmail_query"] = gmail_query.strip()
    if calendar_query.strip():
        body["calendar_query"] = calendar_query.strip()
    return body


HISTORY_COLUMNS: list[dict[str, str]] = [
    {"name": "timestamp", "label": "Time", "field": "timestamp", "align": "left"},
    {"name": "tool", "label": "Tool", "field": "tool", "align": "left"},
    {"name": "event_type", "label": "Event", "field": "event_type", "align": "left"},
    {"name": "summary", "label": "Summary", "field": "summary", "align": "left"},
]


def format_pending_action(action: dict[str, Any]) -> str:
    return f"{action['tool']}.{action['method']}: {action['description']}"


def format_result(result: dict[str, Any] | None) -> str:
    """Plain-language rendering of a RunOutcome's final_result for the
    dashboard, distinguishing "nothing was proposed", "you rejected it",
    and "it ran" without the viewer needing to parse raw JSON.
    """
    if result is None:
        return ""
    if not result.get("executed"):
        reason = result.get("reason", "not executed")
        if reason == "no_action_proposed":
            return "No action was needed."
        if reason == "rejected":
            return "Action was rejected — nothing was sent or changed."
        return f"Not executed ({reason})."
    return f"Done: {result.get('description', 'action executed')}"
