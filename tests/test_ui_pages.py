"""End-to-end tests for the actual NiceGUI dashboard pages (apm.ui.app),
using NiceGUI's official `user` test fixture (registered in the root
conftest.py). This drives real page code -- typing into "Ask APM",
clicking it, the orders list, the approval card's Approve/Reject buttons
-- rather than only the pure logic in apm.ui.logic or the API in
isolation, closing a gap those two suites don't cover on their own.

The dashboard talks to the FastAPI backend over real HTTP
(httpx.AsyncClient); here `patched_backend` monkeypatches httpx.AsyncClient
to route through an in-process fake API app instead of a real server, so
these tests need no live credentials, Anthropic API key, or running
server -- same fake Gmail/Calendar clients and fake reasoner/intent
parser used throughout the rest of the test suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver
from nicegui import ui
from nicegui.testing import User

from apm.agent.graph import build_graph
from apm.agent.intent import ParsedIntent
from apm.agent.reasoner import ProposedAction, ReasoningResult
from apm.api.app import create_app
from apm.api.dependencies import get_graph, get_intent_parser, get_state_store
from apm.state.store import StateStore
from apm.tools.calendar_tool import CalendarTool
from apm.tools.gmail_tool import GmailTool
from tests.test_agent_graph import FakeReasoner
from tests.test_api import FakeIntentParser
from tests.test_calendar_tool import FakeCalendarClient
from tests.test_gmail_tool import FakeGmailClient


@pytest.fixture
def patched_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a fake FastAPI app (same fixtures as test_api.py) and route
    every httpx.AsyncClient the dashboard creates to it in-process,
    instead of a real running server, by injecting an ASGI transport.

    Returns a dict with a `build(reasoning_result, intent)` function to
    finish wiring the fake backend (deferred so each test can supply its
    own scenario), plus the fake clients/store for assertions.
    """
    store = StateStore(tmp_path / "state.json")
    gmail_client = FakeGmailClient([])
    calendar_client = FakeCalendarClient([])
    tools = {
        "gmail": GmailTool(store, gmail_client),
        "google_calendar": CalendarTool(store, calendar_client),
    }

    def build(reasoning_result: ReasoningResult, intent: ParsedIntent) -> None:
        graph = build_graph(tools, FakeReasoner(reasoning_result), store, checkpointer=MemorySaver())
        app = create_app()
        app.dependency_overrides[get_graph] = lambda: graph
        app.dependency_overrides[get_state_store] = lambda: store
        app.dependency_overrides[get_intent_parser] = lambda: FakeIntentParser(intent)

        real_async_client = httpx.AsyncClient

        class _PatchedAsyncClient(real_async_client):  # type: ignore[misc]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs["transport"] = httpx.ASGITransport(app=app)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", _PatchedAsyncClient)

    return {"build": build, "store": store, "gmail_client": gmail_client, "calendar_client": calendar_client}


async def test_home_page_loads_and_shows_api_connected(user: User, patched_backend) -> None:
    patched_backend["build"](
        ReasoningResult(summary="x", proposed_action=None),
        ParsedIntent(process_id="order-1", gmail_query="order"),
    )

    await user.open("/")

    await user.should_see("Ask APM")
    await user.should_see("API connected")


async def test_ask_with_no_action_navigates_to_order_with_summary(user: User, patched_backend) -> None:
    patched_backend["build"](
        ReasoningResult(summary="Everything is on track.", proposed_action=None),
        ParsedIntent(process_id="order-1", gmail_query="newer_than:30d"),
    )

    await user.open("/")
    user.find(kind=ui.input).type("any update on order-1?")
    user.find(kind=ui.button, content="Ask").click()

    await user.should_see("Everything is on track.", retries=20)
    await user.should_not_see("Approval needed")


async def test_full_email_approval_flow_through_the_ui(user: User, patched_backend) -> None:
    proposed = ProposedAction(
        tool="gmail",
        method="send_email",
        description="Send a follow-up about the delay",
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."},
    )
    patched_backend["build"](
        ReasoningResult(summary="There is a delay.", proposed_action=proposed, category="shipment_delay"),
        ParsedIntent(process_id="order-401", gmail_query="order 401"),
    )

    await user.open("/")
    user.find(kind=ui.input).type("chase up order 401")
    user.find(kind=ui.button, content="Ask").click()

    await user.should_see("Approval needed", retries=20)
    await user.should_see("Shipment Delay")  # category badge
    await user.should_see("customer@realcorp.io")  # friendly field, not a raw dict dump

    user.find("Approve").click()

    await user.should_see("Done:", retries=20)
    assert patched_backend["gmail_client"].sent == [
        {"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."}
    ]


async def test_calendar_rejection_flow_through_the_ui(user: User, patched_backend) -> None:
    proposed = ProposedAction(
        tool="google_calendar",
        method="create_event",
        description="Create a renewal reminder",
        payload={"title": "Renewal call", "start": "2026-09-10T15:00:00Z", "end": "2026-09-10T15:30:00Z"},
    )
    patched_backend["build"](
        ReasoningResult(summary="Renewal is coming up.", proposed_action=proposed, category="renewal_reminder"),
        ParsedIntent(process_id="order-402", calendar_query="renewal"),
    )

    await user.open("/")
    user.find(kind=ui.input).type("check the renewal for order 402")
    user.find(kind=ui.button, content="Ask").click()

    await user.should_see("Approval needed", retries=20)

    user.find("Reject").click()

    await user.should_see("rejected", retries=20)
    assert patched_backend["calendar_client"].inserted == []


async def test_orders_list_shows_created_order_with_status_and_category(user: User, patched_backend) -> None:
    proposed = ProposedAction(
        tool="gmail",
        method="send_email",
        description="Send a follow-up",
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Delayed."},
    )
    patched_backend["build"](
        ReasoningResult(summary="There is a delay.", proposed_action=proposed, category="shipment_delay"),
        ParsedIntent(process_id="order-403", gmail_query="order 403"),
    )

    await user.open("/")
    user.find(kind=ui.input).type("chase up order 403")
    user.find(kind=ui.button, content="Ask").click()
    await user.should_see("Approval needed", retries=20)

    await user.open("/")

    await user.should_see("order-403", retries=20)
    await user.should_see("Needs approval")
    await user.should_see("Shipment Delay")
