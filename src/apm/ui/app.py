"""NiceGUI dashboard for APM.

Talks to the phase 6a FastAPI backend over HTTP — it never imports
apm.agent.graph or the tool connectors directly — so this is a genuinely
separate presentation-layer client of the API, as decided when picking
FastAPI + NiceGUI for phase 6. Pure request/response logic lives in
apm.ui.logic so it's unit-tested without a browser; this module is just
the page wiring.

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
    build_start_request,
    format_action_details,
    format_pending_action,
    format_result,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

API_BASE_URL = os.environ.get("APM_API_BASE_URL", "http://localhost:8000")
UI_PORT = int(os.environ.get("APM_UI_PORT", "8080"))


class DashboardState:
    def __init__(self) -> None:
        self.process_id: str = ""
        self.pending_action: dict | None = None
        self.final_result: dict | None = None


@ui.page("/")
async def index() -> None:
    state = DashboardState()

    ui.label("APM — Agentic Process Management").classes("text-2xl font-bold")
    ui.label('"Don\'t operate the tools. Talk to the business."').classes("text-sm text-gray-500 mb-4")

    api_status = ui.badge("checking API...", color="grey")

    async def check_health() -> None:
        try:
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=5) as client:
                response = await client.get("/health")
                response.raise_for_status()
            api_status.set_text(f"API connected ({API_BASE_URL})")
            api_status.props("color=green")
        except httpx.HTTPError:
            api_status.set_text(f"API unreachable ({API_BASE_URL})")
            api_status.props("color=red")

    ui.timer(0.1, check_health, once=True)

    with ui.row().classes("items-end gap-4 mt-4"):
        process_id_input = ui.input("Process ID", placeholder="order-123").classes("w-40")
        gmail_query_input = ui.input("Gmail query", placeholder="newer_than:30d").classes("w-56")
        calendar_query_input = ui.input("Calendar query", placeholder="renewal").classes("w-56")

    error_label = ui.label("").classes("text-red-600")
    summary_label = ui.label("").classes("text-lg mt-2")

    @ui.refreshable
    def pending_action_panel() -> None:
        if not state.pending_action:
            return
        action = state.pending_action
        with ui.card().classes("border-2 border-amber-400 mt-2"):
            ui.label("Approval needed").classes("font-bold text-amber-700")
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
    def result_panel() -> None:
        if state.final_result is not None:
            ui.label(format_result(state.final_result)).classes("text-md mt-2")

    ui.label("History").classes("text-lg font-bold mt-6")

    @ui.refreshable
    def history_panel(rows: list[dict] | None = None) -> None:
        ui.table(columns=HISTORY_COLUMNS, rows=rows or []).classes("w-full")

    pending_action_panel()
    result_panel()
    history_panel()

    async def refresh_history() -> None:
        if not state.process_id:
            return
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30) as client:
            response = await client.get(f"/processes/{state.process_id}/history")
            response.raise_for_status()
            history_panel.refresh(rows=response.json())

    async def handle_start() -> None:
        state.process_id = process_id_input.value.strip()
        if not state.process_id:
            error_label.set_text("Process ID is required.")
            return

        body = build_start_request(gmail_query_input.value, calendar_query_input.value)
        if not body:
            error_label.set_text("Enter at least one of Gmail query / Calendar query.")
            return

        error_label.set_text("")
        try:
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=60) as client:
                response = await client.post(f"/processes/{state.process_id}/start", json=body)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            error_label.set_text(f"API error: {exc.response.text}")
            return
        except httpx.HTTPError as exc:
            error_label.set_text(f"Could not reach API: {exc}")
            return

        summary_label.set_text(data.get("summary") or "")
        state.pending_action = data.get("pending_action")
        state.final_result = data.get("final_result")
        pending_action_panel.refresh()
        result_panel.refresh()
        await refresh_history()

    async def handle_decision(approved: bool) -> None:
        try:
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=60) as client:
                response = await client.post(
                    f"/processes/{state.process_id}/decision", json={"approved": approved}
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            error_label.set_text(f"Could not reach API: {exc}")
            return

        state.pending_action = None
        state.final_result = data.get("final_result")
        pending_action_panel.refresh()
        result_panel.refresh()
        await refresh_history()

    ui.button("Start", color="primary", on_click=handle_start).classes("mt-2")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="APM Dashboard", port=UI_PORT, reload=False)
