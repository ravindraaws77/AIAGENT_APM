"""NiceGUI dashboard for APM.

Talks to the phase 6a/7a FastAPI backend over HTTP — it never imports
apm.agent.graph or the tool connectors directly — so this is a genuinely
separate presentation-layer client of the API, as decided when picking
FastAPI + NiceGUI for phase 6. Pure request/response logic lives in
apm.ui.logic so it's unit-tested without a browser; this module is just
the page wiring.

Phase 7b: replaces the old single-page form (process ID + raw Gmail/
Calendar query fields) with a single free-text prompt bar over POST
/query, an orders list (from GET /processes) as the home page, and a
per-order detail page for reviewing history and responding to an
approval request.

Run the backend first, then this:
    uvicorn apm.api.app:app --port 8000
    python -m apm.ui.app
"""

from __future__ import annotations

import os

import httpx
from nicegui import ui

from apm.ui.logic import (
    HISTORY_COLUMNS,
    build_query_request,
    category_color,
    format_action_details,
    format_category_label,
    format_pending_action,
    format_result,
    normalize_pending_action,
    prepare_history_rows,
    prepare_order_rows,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

API_BASE_URL = os.environ.get("APM_API_BASE_URL", "http://localhost:8000")
UI_PORT = int(os.environ.get("APM_UI_PORT", "8080"))


async def _check_health(badge) -> None:
    try:
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=5) as client:
            response = await client.get("/health")
            response.raise_for_status()
        badge.set_text(f"API connected ({API_BASE_URL})")
        badge.props("color=green")
    except httpx.HTTPError:
        badge.set_text(f"API unreachable ({API_BASE_URL})")
        badge.props("color=red")


def _page_header(subtitle: str) -> None:
    ui.label("APM — Agentic Process Management").classes("text-2xl font-bold")
    ui.label(subtitle).classes("text-sm text-gray-500 mb-4")


@ui.page("/")
async def index() -> None:
    _page_header('"Don\'t operate the tools. Talk to the business."')

    api_status = ui.badge("checking API...", color="grey")
    ui.timer(0.1, lambda: _check_health(api_status), once=True)

    query_error = ui.label("").classes("text-red-600")
    with ui.row().classes("items-end gap-2 w-full mt-4"):
        query_input = ui.input(
            "Ask APM",
            placeholder="e.g. 'chase up order 4521' or 'check the Acme renewal'",
        ).classes("flex-grow")
        ask_button = ui.button("Ask", color="primary")

    ui.label("Orders").classes("text-lg font-bold mt-6")

    @ui.refreshable
    def orders_panel(rows: list[dict] | None = None) -> None:
        if not rows:
            ui.label("No orders yet — ask APM about one above.").classes("text-gray-500")
            return
        for row in rows:
            with ui.card().classes("w-full cursor-pointer hover:shadow-md transition-shadow").on(
                "click", lambda process_id=row["process_id"]: ui.navigate.to(f"/orders/{process_id}")
            ):
                with ui.row().classes("items-center justify-between w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(row["process_id"]).classes("font-bold")
                        if row["category"]:
                            ui.badge(row["category"], color=row["category_color"])
                    ui.badge(row["status_label"], color=row["status_color"])
                if row["summary"]:
                    ui.label(row["summary"]).classes("text-sm text-gray-700 mt-1")
                if row["updated_at"]:
                    ui.label(f"Updated {row['updated_at']}").classes("text-xs text-gray-400 mt-1")

    orders_panel()

    async def refresh_orders() -> None:
        try:
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30) as client:
                response = await client.get("/processes")
                response.raise_for_status()
                orders_panel.refresh(rows=prepare_order_rows(response.json()))
        except httpx.HTTPError as exc:
            query_error.set_text(f"Could not load orders: {exc}")

    ui.timer(0.1, refresh_orders, once=True)

    async def handle_ask() -> None:
        body = build_query_request(query_input.value)
        if body is None:
            query_error.set_text("Type a request first.")
            return

        query_error.set_text("")
        ask_button.disable()
        try:
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=60) as client:
                response = await client.post("/query", json=body)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            query_error.set_text(f"API error: {exc.response.text}")
            return
        except httpx.HTTPError as exc:
            query_error.set_text(f"Could not reach API: {exc}")
            return
        finally:
            ask_button.enable()

        ui.navigate.to(f"/orders/{data['process_id']}")

    ask_button.on_click(handle_ask)


@ui.page("/orders/{process_id}")
async def order_detail(process_id: str) -> None:
    ui.link("← Orders", "/").classes("text-sm")
    _page_header(f"Order: {process_id}")

    api_status = ui.badge("checking API...", color="grey")
    ui.timer(0.1, lambda: _check_health(api_status), once=True)

    error_label = ui.label("").classes("text-red-600")
    summary_label = ui.label("").classes("text-lg mt-2")

    @ui.refreshable
    def pending_action_panel(action: dict | None = None) -> None:
        if not action:
            return
        with ui.card().classes("border-2 border-amber-400 mt-2"):
            with ui.row().classes("items-center gap-2"):
                ui.label("Approval needed").classes("font-bold text-amber-700")
                category = action.get("category") or "other"
                ui.badge(format_category_label(category), color=category_color(category))
            ui.label(format_pending_action(action))
            with ui.column().classes("gap-1 w-full mt-1"):
                for label, value in format_action_details(action):
                    with ui.row().classes("gap-2 items-start w-full"):
                        ui.label(f"{label}:").classes("font-semibold w-20 shrink-0")
                        ui.label(value).classes("whitespace-pre-wrap")
            with ui.row():
                ui.button("Approve", color="green", on_click=lambda: handle_decision(True))
                ui.button("Reject", color="red", on_click=lambda: handle_decision(False))

    @ui.refreshable
    def result_panel(result: dict | None = None) -> None:
        if result is not None:
            ui.label(format_result(result)).classes("text-md mt-2")

    ui.label("History").classes("text-lg font-bold mt-6")

    @ui.refreshable
    def history_panel(rows: list[dict] | None = None) -> None:
        table = ui.table(columns=HISTORY_COLUMNS, rows=rows or []).classes("w-full")
        # Renders the category column as a colored badge (category_color,
        # set by prepare_history_rows) instead of plain text, so a
        # recurring issue type is visually obvious scanning down the
        # table -- the whole point of color-coding by category.
        table.add_slot(
            "body-cell-category",
            r"""
            <q-td :props="props">
                <q-badge v-if="props.value" :color="props.row.category_color">{{ props.value }}</q-badge>
            </q-td>
            """,
        )

    pending_action_panel()
    result_panel()
    history_panel()

    async def refresh_history() -> None:
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30) as client:
            response = await client.get(f"/processes/{process_id}/history")
            response.raise_for_status()
            history_panel.refresh(rows=prepare_history_rows(response.json()))

    async def handle_decision(approved: bool) -> None:
        try:
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=60) as client:
                response = await client.post(
                    f"/processes/{process_id}/decision", json={"approved": approved}
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            error_label.set_text(f"Could not reach API: {exc}")
            return

        pending_action_panel.refresh(action=None)
        result_panel.refresh(result=data.get("final_result"))
        await refresh_history()

    async def load() -> None:
        try:
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30) as client:
                status_response = await client.get(f"/processes/{process_id}/status")
                if status_response.status_code == 404:
                    error_label.set_text(f"No such order: {process_id}")
                    return
                status_response.raise_for_status()
                status = status_response.json()

                pending_response = await client.get(f"/processes/{process_id}/pending")
                pending_response.raise_for_status()
                pending = pending_response.json()

                history_response = await client.get(f"/processes/{process_id}/history")
                history_response.raise_for_status()
                history = history_response.json()
        except httpx.HTTPError as exc:
            error_label.set_text(f"Could not reach API: {exc}")
            return

        summary_label.set_text(status.get("summary") or "")
        pending_action_panel.refresh(action=normalize_pending_action(pending[0]) if pending else None)
        result_panel.refresh(result=status.get("result"))
        history_panel.refresh(rows=prepare_history_rows(history))

    ui.timer(0.1, load, once=True)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="APM Dashboard", port=UI_PORT, reload=False)
