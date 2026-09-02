"""Tests for the FastAPI backend. Uses the real graph (build_graph) wired
to fake tools and a fake reasoner — the same fixtures test_agent_graph.py
uses — injected via FastAPI's dependency_overrides, so no live
credentials, Anthropic API key, or running server is needed.
"""

from pathlib import Path

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from apm.agent.graph import build_graph
from apm.agent.reasoner import ProposedAction, ReasoningResult
from apm.api.app import create_app
from apm.api.dependencies import get_graph, get_state_store
from apm.state.store import StateStore
from apm.tools.calendar_tool import CalendarTool
from apm.tools.gmail_tool import GmailTool
from tests.test_agent_graph import FakeReasoner
from tests.test_calendar_tool import FakeCalendarClient
from tests.test_gmail_tool import FakeGmailClient


def _client(tmp_path: Path, reasoning_result: ReasoningResult):
    store = StateStore(tmp_path / "state.json")
    gmail_client = FakeGmailClient([])
    calendar_client = FakeCalendarClient([])
    tools = {
        "gmail": GmailTool(store, gmail_client),
        "google_calendar": CalendarTool(store, calendar_client),
    }
    graph = build_graph(tools, FakeReasoner(reasoning_result), store, checkpointer=MemorySaver())

    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    app.dependency_overrides[get_state_store] = lambda: store
    return TestClient(app), store, gmail_client, calendar_client


def test_health() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_start_process_requires_a_query(tmp_path: Path) -> None:
    client, *_ = _client(tmp_path, ReasoningResult(summary="x", proposed_action=None))
    response = client.post("/processes/order-1/start", json={})
    assert response.status_code == 400


def test_start_process_with_no_proposed_action(tmp_path: Path) -> None:
    client, store, gmail_client, _ = _client(
        tmp_path, ReasoningResult(summary="Everything is on track.", proposed_action=None)
    )

    response = client.post("/processes/order-1/start", json={"gmail_query": "newer_than:30d"})

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "Everything is on track."
    assert data["pending_action"] is None
    assert data["final_result"] == {"executed": False, "reason": "no_action_proposed"}
    assert gmail_client.sent == []


def test_full_approval_flow_through_the_api(tmp_path: Path) -> None:
    proposed = ProposedAction(
        tool="gmail",
        method="send_email",
        description="Send a follow-up email about the delay",
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."},
    )
    client, store, gmail_client, _ = _client(
        tmp_path, ReasoningResult(summary="There is a delay.", proposed_action=proposed)
    )

    start_response = client.post("/processes/order-1/start", json={"gmail_query": "order"})
    assert start_response.status_code == 200
    start_data = start_response.json()
    assert start_data["pending_action"]["tool"] == "gmail"
    assert start_data["pending_action"]["method"] == "send_email"
    assert gmail_client.sent == []  # not executed yet

    pending = client.get("/processes/order-1/pending").json()
    assert len(pending) == 1

    decision_response = client.post("/processes/order-1/decision", json={"approved": True})
    assert decision_response.status_code == 200
    decision_data = decision_response.json()
    assert decision_data["final_result"]["executed"] is True
    assert len(gmail_client.sent) == 1

    assert client.get("/processes/order-1/pending").json() == []


def test_rejection_through_the_api_does_not_execute(tmp_path: Path) -> None:
    proposed = ProposedAction(
        tool="google_calendar",
        method="create_event",
        description="Create a renewal reminder",
        payload={"title": "Renewal call", "start": "2026-09-10T15:00:00Z", "end": "2026-09-10T15:30:00Z"},
    )
    client, store, _, calendar_client = _client(
        tmp_path, ReasoningResult(summary="Renewal is coming up.", proposed_action=proposed)
    )

    client.post("/processes/order-1/start", json={"calendar_query": "renewal"})
    decision_response = client.post("/processes/order-1/decision", json={"approved": False})

    assert decision_response.json()["final_result"] == {"executed": False, "reason": "rejected"}
    assert calendar_client.inserted == []


def test_status_and_history_endpoints(tmp_path: Path) -> None:
    client, *_ = _client(tmp_path, ReasoningResult(summary="No issues.", proposed_action=None))

    client.post("/processes/order-1/start", json={"gmail_query": "order"})

    status_response = client.get("/processes/order-1/status")
    assert status_response.status_code == 200
    assert status_response.json()["stage"] == "done"

    history_response = client.get("/processes/order-1/history")
    assert history_response.status_code == 200
    assert len(history_response.json()) > 0

    processes_response = client.get("/processes")
    assert processes_response.status_code == 200
    assert len(processes_response.json()) == 1


def test_status_404_for_unknown_process(tmp_path: Path) -> None:
    client, *_ = _client(tmp_path, ReasoningResult(summary="x", proposed_action=None))
    response = client.get("/processes/does-not-exist/status")
    assert response.status_code == 404


def test_start_returns_clean_502_on_upstream_failure(tmp_path: Path) -> None:
    """Reproduces the real scenario: a tool call fails (e.g. a transient
    network error exhausted its retries) mid-graph. The API must return
    a clean, readable error instead of an unhandled 500 with a raw
    Python traceback.
    """

    class BrokenGmailClient:
        def list_message_ids(self, query: str, max_results: int):
            raise ConnectionError("simulated: connection aborted by host")

        def get_message(self, message_id: str):
            raise ConnectionError("simulated: connection aborted by host")

        def send_message(self, to: str, subject: str, body: str):
            raise ConnectionError("simulated: connection aborted by host")

    store = StateStore(tmp_path / "state.json")
    tools = {
        "gmail": GmailTool(store, BrokenGmailClient()),
        "google_calendar": CalendarTool(store, FakeCalendarClient([])),
    }
    graph = build_graph(
        tools, FakeReasoner(ReasoningResult(summary="x", proposed_action=None)), store, checkpointer=MemorySaver()
    )
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    app.dependency_overrides[get_state_store] = lambda: store
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/processes/order-1/start", json={"gmail_query": "order"})

    assert response.status_code == 502
    assert "connection aborted" in response.json()["detail"].lower()
