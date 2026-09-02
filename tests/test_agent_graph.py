"""Tests for the agent graph's control flow — the actual heart of the
non-negotiable rule: a proposed write/action must not execute until a
human decision arrives via resume_process. Uses the real tool classes
(GmailTool, CalendarTool, ExcelTool) wired to in-memory fake clients, and
a fake reasoner, so this needs no live credentials or Anthropic API key.
"""

from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from apm.agent.graph import build_graph, resume_process, start_process
from apm.agent.reasoner import ProposedAction, ReasoningResult
from apm.state.store import StateStore
from apm.tools.calendar_tool import CalendarTool
from apm.tools.gmail_tool import GmailTool
from tests.test_calendar_tool import FakeCalendarClient
from tests.test_gmail_tool import FakeGmailClient


class FakeReasoner:
    """Returns a pre-set ReasoningResult regardless of input — lets tests
    control exactly what the "intelligence layer" proposes without any
    API call.
    """

    def __init__(self, result: ReasoningResult) -> None:
        self._result = result

    def reason(self, process_id: str, context: dict[str, Any]) -> ReasoningResult:
        return self._result


def _build(tmp_path: Path, reasoning_result: ReasoningResult):
    store = StateStore(tmp_path / "state.json")
    gmail_client = FakeGmailClient([])
    gmail_tool = GmailTool(store, gmail_client)
    calendar_client = FakeCalendarClient([])
    calendar_tool = CalendarTool(store, calendar_client)

    tools = {"gmail": gmail_tool, "google_calendar": calendar_tool}
    reasoner = FakeReasoner(reasoning_result)
    graph = build_graph(tools, reasoner, store, checkpointer=MemorySaver())
    return graph, store, gmail_client, calendar_client


def test_no_proposed_action_runs_straight_through(tmp_path: Path) -> None:
    graph, store, gmail_client, _ = _build(
        tmp_path, ReasoningResult(summary="Everything is on track.", proposed_action=None)
    )

    outcome = start_process(graph, "order-1", queries={})

    assert outcome.pending_action is None
    assert outcome.final_result == {"executed": False, "reason": "no_action_proposed"}
    assert outcome.summary == "Everything is on track."
    assert gmail_client.sent == []

    status = store.get_status("order-1")
    assert status["stage"] == "done"


def test_proposed_action_pauses_for_approval(tmp_path: Path) -> None:
    proposed = ProposedAction(
        tool="gmail",
        method="send_email",
        description="Send a follow-up email about the delay",
        payload={"to": "customer@example.com", "subject": "Update", "body": "Your order is delayed."},
    )
    graph, store, gmail_client, _ = _build(
        tmp_path, ReasoningResult(summary="There is a delay.", proposed_action=proposed)
    )

    outcome = start_process(graph, "order-1", queries={})

    assert outcome.final_result is None
    assert outcome.pending_action is not None
    assert outcome.pending_action["tool"] == "gmail"
    assert outcome.pending_action["method"] == "send_email"

    # Nothing has actually happened yet.
    assert gmail_client.sent == []
    assert len(store.list_pending_actions("order-1")) == 1


def test_approval_executes_the_action(tmp_path: Path) -> None:
    proposed = ProposedAction(
        tool="gmail",
        method="send_email",
        description="Send a follow-up email about the delay",
        payload={"to": "customer@example.com", "subject": "Update", "body": "Your order is delayed."},
    )
    graph, store, gmail_client, _ = _build(
        tmp_path, ReasoningResult(summary="There is a delay.", proposed_action=proposed)
    )

    start_process(graph, "order-1", queries={})
    outcome = resume_process(graph, "order-1", approved=True)

    assert outcome.final_result["executed"] is True
    assert gmail_client.sent == [
        {"to": "customer@example.com", "subject": "Update", "body": "Your order is delayed."}
    ]
    assert store.list_pending_actions("order-1") == []

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_approved" for e in events)
    assert any(e["event_type"] == "action_executed" for e in events)

    status = store.get_status("order-1")
    assert status["stage"] == "done"
    assert status["result"]["executed"] is True


def test_rejection_does_not_execute_the_action(tmp_path: Path) -> None:
    proposed = ProposedAction(
        tool="google_calendar",
        method="create_event",
        description="Create a renewal reminder",
        payload={"title": "Renewal call", "start": "2026-09-10T15:00:00Z", "end": "2026-09-10T15:30:00Z"},
    )
    graph, store, _, calendar_client = _build(
        tmp_path, ReasoningResult(summary="Renewal is coming up.", proposed_action=proposed)
    )

    start_process(graph, "order-1", queries={})
    outcome = resume_process(graph, "order-1", approved=False)

    assert outcome.final_result == {"executed": False, "reason": "rejected"}
    assert calendar_client.inserted == []
    assert store.list_pending_actions("order-1") == []

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_rejected" for e in events)
    assert not any(e["event_type"] == "action_executed" for e in events)


def test_fetch_node_calls_configured_tools_and_persists_status(tmp_path: Path) -> None:
    from tests.test_gmail_tool import _raw_message

    graph, store, gmail_client, _ = _build(
        tmp_path, ReasoningResult(summary="No issues found.", proposed_action=None)
    )
    gmail_client._messages["m1"] = _raw_message(  # noqa: SLF001 - test setup convenience
        "m1", "customer@example.com", "Order question", "When will it ship?", "Mon, 1 Sep 2026 10:00:00 +0000"
    )

    outcome = start_process(graph, "order-1", queries={"gmail": {"query": "order", "max_results": 5}})

    assert outcome.summary == "No issues found."
    status = store.get_status("order-1")
    assert "gmail" in status["fetched"]
    assert status["fetched"]["gmail"][0]["subject"] == "Order question"
