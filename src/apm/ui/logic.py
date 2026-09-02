"""Pure, framework-free helpers for the NiceGUI dashboard (app.py).

Kept separate from app.py — the actual NiceGUI page wiring — so this
logic is unit-testable without a browser, NiceGUI's test harness, or a
running API server. Mirrors the rest of the repo's pattern of separating
protocol/pure-logic from real I/O (e.g. the tool connectors' *Client
protocols vs. their real API-backed implementations).
"""

from __future__ import annotations

import zlib
from typing import Any


def build_query_request(text: str) -> dict[str, str] | None:
    """Build the POST /query request body from the dashboard's single
    free-text prompt bar. None if the box is blank — the caller should
    treat that as "nothing to ask" and not call the API.
    """
    text = text.strip()
    return {"text": text} if text else None


HISTORY_COLUMNS: list[dict[str, str]] = [
    {"name": "timestamp", "label": "Time", "field": "timestamp", "align": "left"},
    {"name": "tool", "label": "Tool", "field": "tool", "align": "left"},
    {"name": "event_type", "label": "Event", "field": "event_type", "align": "left"},
    {"name": "category", "label": "Category", "field": "category", "align": "left"},
    {"name": "summary", "label": "Summary", "field": "summary", "align": "left"},
]

# A handful of expected categories (see apm.agent.reasoner.SYSTEM_PROMPT)
# get curated, meaningful colors. Anything else -- the model is free to
# invent its own short slug -- still gets *a* color, picked
# deterministically (same slug always maps to the same color, stable
# across restarts) from a fallback palette, rather than no color at all.
_CURATED_CATEGORY_COLORS: dict[str, str] = {
    "shipment_delay": "red",
    "renewal_reminder": "blue",
    "missing_information": "orange",
    "customer_inquiry": "purple",
    "payment_issue": "deep-orange",
    "other": "grey",
}
_FALLBACK_CATEGORY_COLORS: list[str] = ["teal", "indigo", "pink", "brown", "cyan", "lime"]


def category_color(category: str) -> str:
    """A stable Quasar/NiceGUI color name for a category slug, so the
    same kind of issue always renders with the same color everywhere in
    the dashboard -- the point being to make a recurring pattern (e.g.
    three shipment delays in a row) visually obvious when scanning the
    history table, not just readable one row at a time.

    Uses crc32 rather than Python's built-in hash() for the fallback
    palette: hash() is salted per-process for strings, which would give
    a different color to the same category every time the app restarts.
    """
    if category in _CURATED_CATEGORY_COLORS:
        return _CURATED_CATEGORY_COLORS[category]
    index = zlib.crc32(category.encode("utf-8")) % len(_FALLBACK_CATEGORY_COLORS)
    return _FALLBACK_CATEGORY_COLORS[index]


def format_category_label(category: str) -> str:
    return category.replace("_", " ").title()


def prepare_history_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten each raw history event's nested `details.category` (set by
    apm.state.store.StateStore.add_pending_action/resolve_pending_action)
    into top-level `category`/`category_color` fields the History table
    can bind directly to. Rows with no category (e.g. plain `read`
    events) get an empty string, which the table's cell template treats
    as "no badge" rather than showing a stray empty chip.
    """
    prepared = []
    for row in rows:
        category = (row.get("details") or {}).get("category") or ""
        prepared.append(
            {
                **row,
                "category": format_category_label(category) if category else "",
                "category_color": category_color(category) if category else "",
            }
        )
    return prepared


def format_pending_action(action: dict[str, Any]) -> str:
    return f"{action['tool']}.{action['method']}: {action['description']}"


def format_action_details(action: dict[str, Any]) -> list[tuple[str, str]]:
    """Turn a proposed action's payload into an ordered list of
    (label, value) pairs for friendly display in the approval card,
    instead of a raw JSON/dict dump. Tailored to each method's payload
    shape (see apm.agent.reasoner.SYSTEM_PROMPT's "Payload shapes"),
    since a person approving "send an email" wants To/Subject/Body, not
    Python dict syntax with escaped newlines.

    Falls back to raw key/value pairs for a method this doesn't
    recognize yet, so a future action type still displays something
    rather than being silently dropped.
    """
    payload = action.get("payload") or {}
    method = action.get("method")

    if method == "send_email":
        return [
            ("To", str(payload.get("to", ""))),
            ("Subject", str(payload.get("subject", ""))),
            ("Body", str(payload.get("body", ""))),
        ]

    if method == "create_event":
        details = [
            ("Title", str(payload.get("title", ""))),
            ("Start", str(payload.get("start", ""))),
            ("End", str(payload.get("end", ""))),
        ]
        attendees = payload.get("attendees") or []
        if attendees:
            details.append(("Attendees", ", ".join(attendees)))
        if payload.get("location"):
            details.append(("Location", str(payload["location"])))
        return details

    if method == "write_range":
        values = payload.get("values") or []
        return [
            ("Sheet", str(payload.get("sheet_name", ""))),
            ("Range", str(payload.get("address", ""))),
            ("Rows", str(len(values))),
        ]

    return [(str(key), str(value)) for key, value in payload.items()]


def order_status(process: dict[str, Any]) -> tuple[str, str]:
    """Derive a (label, color) status pill for one process's persisted
    status record (apm.state.store.StateStore.set_status).

    Relies on apm.agent.graph's stage sequence: fetch_node sets "fetched",
    reason_node sets "summarized", and execute_node is the only thing
    that ever sets "done" -- which happens exactly once, after a human
    decision resolves the approval interrupt (or immediately, if the
    reasoner proposed nothing). So a process stuck at "summarized" -- it
    never advances to "done" on its own -- means the graph is paused at
    the approval interrupt: exactly the moment the orders list exists to
    surface, without a separate query against /pending for every row.
    """
    stage = process.get("stage")
    if stage == "summarized":
        return "Needs approval", "amber"
    if stage == "done":
        result = process.get("result") or {}
        if result.get("executed"):
            return "Done", "green"
        if result.get("reason") == "rejected":
            return "Rejected", "red"
        if result.get("reason") == "no_action_proposed":
            return "No action needed", "grey"
        return "Done", "green"
    return "In progress", "blue"


def prepare_order_rows(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn raw GET /processes records into rows the orders list renders
    directly: a status pill (order_status) plus the same category badge
    styling the History table already uses (category_color,
    format_category_label). Sorted most-recently-updated first, so an
    order that just changed -- especially one that now needs a decision
    -- surfaces at the top instead of wherever it happened to be created.
    """
    rows = []
    for process in processes:
        category = process.get("category") or ""
        status_label, status_color = order_status(process)
        rows.append(
            {
                "process_id": process["process_id"],
                "category": format_category_label(category) if category else "",
                "category_color": category_color(category) if category else "",
                "status_label": status_label,
                "status_color": status_color,
                "summary": process.get("summary") or "",
                "updated_at": process.get("updated_at") or "",
            }
        )
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    return rows


def normalize_pending_action(record: dict[str, Any]) -> dict[str, Any]:
    """GET /processes/{id}/pending returns apm.state.store's persisted
    pending-action records, whose `payload` field is the *entire*
    proposed-action dict apm.agent.graph's propose_node stored (tool,
    method, description, and its own nested payload) -- not just the
    tool call's arguments. This flattens one record into the
    {tool, method, description, payload, category} shape
    format_pending_action/format_action_details already expect, which is
    what the graph's live interrupt() payload looks like directly (the
    shape the single-page dashboard used to get straight from
    POST /start's response, before there was a separate detail page that
    has to reconstruct it from a fresh GET instead).
    """
    proposed = record.get("payload") or {}
    return {
        "tool": proposed.get("tool", record.get("tool")),
        "method": proposed.get("method"),
        "description": proposed.get("description", record.get("description")),
        "payload": proposed.get("payload") or {},
        "category": record.get("category", "other"),
    }


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
