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
from apm.tools.excel_file_tool import ExcelFileTool
from apm.tools.gmail_tool import GmailTool
from tests.test_calendar_tool import FakeCalendarClient
from tests.test_excel_file_tool import FakeWorkbookSource, _sample_workbook_bytes
from tests.test_gmail_tool import FakeGmailClient


class FakeReasoner:
    """Returns a pre-set ReasoningResult regardless of input — lets tests
    control exactly what the "intelligence layer" proposes without any
    API call. Records each call's (process_id, context, request_text) so
    tests can assert on what actually reached the reasoner -- notably
    whether request_text (the user's own free-text ask) got through.
    """

    def __init__(self, result: ReasoningResult) -> None:
        self._result = result
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    def reason(self, process_id: str, context: dict[str, Any], request_text: str | None = None) -> ReasoningResult:
        self.calls.append((process_id, context, request_text))
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
    return graph, store, gmail_client, calendar_client, reasoner


def _build_with_excel(tmp_path: Path, reasoning_result: ReasoningResult):
    """Same as _build, plus an excel_file tool bound to a fake workbook
    source — for business scenarios that read from or write to a
    spreadsheet (e.g. a renewals/orders tracker) as part of the flow.
    """
    store = StateStore(tmp_path / "state.json")
    gmail_client = FakeGmailClient([])
    gmail_tool = GmailTool(store, gmail_client)
    calendar_client = FakeCalendarClient([])
    calendar_tool = CalendarTool(store, calendar_client)
    excel_source = FakeWorkbookSource(_sample_workbook_bytes())
    excel_tool = ExcelFileTool(store, excel_source)

    tools = {"gmail": gmail_tool, "google_calendar": calendar_tool, "excel_file": excel_tool}
    reasoner = FakeReasoner(reasoning_result)
    graph = build_graph(tools, reasoner, store, checkpointer=MemorySaver())
    return graph, store, gmail_client, calendar_client, excel_source, reasoner


def test_no_proposed_action_runs_straight_through(tmp_path: Path) -> None:
    graph, store, gmail_client, _, _ = _build(
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
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."},
    )
    graph, store, gmail_client, _, _ = _build(
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
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."},
    )
    graph, store, gmail_client, _, _ = _build(
        tmp_path, ReasoningResult(summary="There is a delay.", proposed_action=proposed)
    )

    start_process(graph, "order-1", queries={})
    outcome = resume_process(graph, "order-1", approved=True)

    assert outcome.final_result["executed"] is True
    assert gmail_client.sent == [
        {"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."}
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
    graph, store, _, calendar_client, _ = _build(
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


def test_category_flows_through_to_pending_action_and_status(tmp_path: Path) -> None:
    proposed = ProposedAction(
        tool="gmail",
        method="send_email",
        description="Send a follow-up email about the delay",
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."},
    )
    graph, store, _, _, _ = _build(
        tmp_path,
        ReasoningResult(summary="There is a delay.", proposed_action=proposed, category="shipment_delay"),
    )

    outcome = start_process(graph, "order-1", queries={})

    assert outcome.pending_action["category"] == "shipment_delay"
    assert store.get_status("order-1")["category"] == "shipment_delay"
    assert store.list_pending_actions("order-1")[0]["category"] == "shipment_delay"


def test_business_scenario_renewal_tracker_read_feeds_status(tmp_path: Path) -> None:
    """A real business flow this connector exists for: the agent reads a
    renewals tracker worksheet as part of deciding what to do next. The
    fetched range should show up in persisted status the same way a
    Gmail search or Calendar search does.
    """
    graph, store, _, _, _, _ = _build_with_excel(
        tmp_path, ReasoningResult(summary="Acme Corp's renewal is due soon.", proposed_action=None)
    )

    outcome = start_process(
        graph, "renewal-acme", queries={"excel_file": {"sheet_name": "Renewals", "address": "A1:B2"}}
    )

    assert outcome.summary == "Acme Corp's renewal is due soon."
    status = store.get_status("renewal-acme")
    assert status["fetched"]["excel_file"]["values"] == [
        ["Customer", "RenewalDate"],
        ["Acme Corp", "2026-10-01"],
    ]


def test_business_scenario_renewal_tracker_update_approved(tmp_path: Path) -> None:
    """Business scenario: after spotting Acme Corp's upcoming renewal in
    the tracker, the agent proposes logging that it's been handled by
    updating the row — a human approves, and the sheet is actually
    updated (mirrors the Gmail send_email/Calendar create_event approval
    tests above, for the Excel connector).
    """
    proposed = ProposedAction(
        tool="excel_file",
        method="write_range",
        description="Mark Acme Corp's renewal as contacted in the tracker",
        payload={"sheet_name": "Renewals", "address": "B2", "values": [["Contacted 2026-09-03"]]},
    )
    graph, store, _, _, excel_source, _ = _build_with_excel(
        tmp_path,
        ReasoningResult(
            summary="Acme Corp's renewal is due soon; logging outreach.",
            proposed_action=proposed,
            category="renewal_reminder",
        ),
    )

    start_process(graph, "renewal-acme", queries={"excel_file": {"sheet_name": "Renewals", "address": "A1:B2"}})
    outcome = resume_process(graph, "renewal-acme", approved=True)

    assert outcome.final_result["executed"] is True
    assert excel_source.write_count == 1

    tool = ExcelFileTool(store, excel_source)
    reread = tool.read_range("renewal-acme", sheet_name="Renewals", address="B2")
    assert reread.values == [["Contacted 2026-09-03"]]

    events = store.list_events("renewal-acme")
    assert any(e["event_type"] == "action_executed" and e["tool"] == "excel_file" for e in events)

    status = store.get_status("renewal-acme")
    assert status["category"] == "renewal_reminder"


def test_business_scenario_renewal_tracker_update_rejected(tmp_path: Path) -> None:
    """Same scenario, but the human rejects the proposed tracker update —
    nothing should be written to the workbook.
    """
    proposed = ProposedAction(
        tool="excel_file",
        method="write_range",
        description="Mark Acme Corp's renewal as contacted in the tracker",
        payload={"sheet_name": "Renewals", "address": "B2", "values": [["Contacted 2026-09-03"]]},
    )
    graph, store, _, _, excel_source, _ = _build_with_excel(
        tmp_path,
        ReasoningResult(summary="Acme Corp's renewal is due soon.", proposed_action=proposed, category="renewal_reminder"),
    )

    start_process(graph, "renewal-acme", queries={"excel_file": {"sheet_name": "Renewals", "address": "A1:B2"}})
    outcome = resume_process(graph, "renewal-acme", approved=False)

    assert outcome.final_result == {"executed": False, "reason": "rejected"}
    assert excel_source.write_count == 0

    events = store.list_events("renewal-acme")
    assert any(e["event_type"] == "action_rejected" for e in events)
    assert not any(e["event_type"] == "action_executed" for e in events)


def test_start_process_passes_request_text_to_the_reasoner(tmp_path: Path) -> None:
    """Regression guard for a real bug: /query used to resolve the
    user's free-text ask (e.g. "update order 223's status to Paid") to a
    process id + queries and then discard the text itself -- the
    reasoner only ever saw the fetched data, with no way to distinguish
    "update this" from a plain "check on this", so it fell back to
    guessing its own idea of a helpful action instead of doing what was
    asked. start_process now threads request_text through to
    reason_node, which passes it to Reasoner.reason as a third argument.
    """
    graph, store, _, _, reasoner = _build(
        tmp_path, ReasoningResult(summary="x", proposed_action=None)
    )

    start_process(graph, "order-223", queries={}, request_text="update order 223's status to Paid")

    assert len(reasoner.calls) == 1
    _process_id, _context, request_text = reasoner.calls[0]
    assert request_text == "update order 223's status to Paid"


def test_start_process_request_text_defaults_to_none(tmp_path: Path) -> None:
    """The /start endpoint (explicit gmail_query/calendar_query fields,
    no free-text box) has no request_text to give -- confirms the
    reasoner still gets called correctly, with None, rather than this
    becoming a required argument that breaks that path.
    """
    graph, store, _, _, reasoner = _build(
        tmp_path, ReasoningResult(summary="x", proposed_action=None)
    )

    start_process(graph, "order-1", queries={})

    assert reasoner.calls[0][2] is None


def test_fetch_node_calls_configured_tools_and_persists_status(tmp_path: Path) -> None:
    from tests.test_gmail_tool import _raw_message

    graph, store, gmail_client, _, _ = _build(
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
