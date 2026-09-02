"""LangGraph orchestration: fetch -> reason/propose -> human-approval
interrupt -> execute -> persist. This is the "Process Orchestration"
layer (layer 4) from docs/architecture.md, and the whole point of the
MVP's end-to-end flow.

The graph is built from injected tools + a reasoner (apm.agent.reasoner)
rather than constructing them internally, so its control flow — including
the interrupt/resume approval gate, the actual non-negotiable rule of
this whole project — can be exercised in tests with fakes and no live
credentials or API key. See tests/test_agent_graph.py.

Usage (see scripts/agent_demo.py for a full example):

    graph = build_graph(tools, reasoner, state_store)
    result = start_process(graph, process_id, queries)
    if result.pending_action:
        ...show result.pending_action to a human, get a decision...
        result = resume_process(graph, process_id, approved=True)
    print(result.summary, result.final_result)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from apm.agent.reasoner import Reasoner
from apm.state.store import StateStore
from apm.tools.base import BaseTool


class GraphState(TypedDict, total=False):
    process_id: str
    queries: dict[str, dict[str, Any]]
    fetched: dict[str, Any]
    summary: str
    proposed_action: dict[str, Any] | None
    pending_action_id: str | None
    decision: bool | None
    result: dict[str, Any] | None


@dataclass(frozen=True)
class RunOutcome:
    """What start_process/resume_process hand back to the caller (a
    script, the phase-6 Streamlit UI, or a test): either the graph is
    paused waiting for a human decision (pending_action set), or it has
    finished (summary/final_result set).
    """

    process_id: str
    summary: str | None
    pending_action: dict[str, Any] | None
    final_result: dict[str, Any] | None


def _config(process_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": process_id}}


def build_graph(tools: dict[str, BaseTool], reasoner: Reasoner, state_store: StateStore, checkpointer: Any):
    """`tools` keys are tool names ("gmail", "google_calendar", "ms_excel");
    any subset may be provided — the fetch node only calls a tool that's
    both present in `tools` and asked for in a run's `queries`.

    `checkpointer` is required explicitly (rather than defaulting to
    MemorySaver inside this function) so callers decide the persistence
    story: MemorySaver for a single script run or a test, a durable
    checkpointer (e.g. SqliteSaver) for the phase-6 UI, which needs a
    paused graph to survive between one Streamlit interaction and the
    next.
    """

    def fetch_node(state: GraphState) -> dict[str, Any]:
        process_id = state["process_id"]
        queries = state.get("queries", {})
        fetched: dict[str, Any] = {}

        if "gmail" in tools and "gmail" in queries:
            emails = tools["gmail"].search_emails(process_id, **queries["gmail"])
            fetched["gmail"] = [e.__dict__ for e in emails]

        if "google_calendar" in tools and "google_calendar" in queries:
            events = tools["google_calendar"].search_events(process_id, **queries["google_calendar"])
            fetched["google_calendar"] = [e.__dict__ for e in events]

        if "ms_excel" in tools and "ms_excel" in queries:
            range_data = tools["ms_excel"].read_range(process_id, **queries["ms_excel"])
            fetched["ms_excel"] = range_data.__dict__

        state_store.set_status(process_id, stage="fetched", fetched=fetched)
        return {"fetched": fetched}

    def reason_node(state: GraphState) -> dict[str, Any]:
        process_id = state["process_id"]
        result = reasoner.reason(process_id, state.get("fetched", {}))
        proposed = (
            {
                "tool": result.proposed_action.tool,
                "method": result.proposed_action.method,
                "description": result.proposed_action.description,
                "payload": result.proposed_action.payload,
            }
            if result.proposed_action
            else None
        )
        state_store.set_status(process_id, stage="summarized", summary=result.summary)
        return {"summary": result.summary, "proposed_action": proposed}

    def propose_node(state: GraphState) -> dict[str, Any]:
        """Records the pending action, if any, exactly once. Deliberately
        kept separate from approval_node: this node runs to completion
        without ever calling interrupt(), so — unlike approval_node — it
        is never replayed, and add_pending_action never double-fires.
        """
        process_id = state["process_id"]
        proposed = state.get("proposed_action")
        if not proposed:
            return {"pending_action_id": None}

        action_record = state_store.add_pending_action(
            process_id=process_id,
            tool=proposed["tool"],
            description=proposed["description"],
            payload=proposed,
        )
        return {"pending_action_id": action_record["id"]}

    def approval_node(state: GraphState) -> dict[str, Any]:
        """The non-negotiable gate: execution physically cannot continue
        past interrupt() without a human decision arriving via
        Command(resume=...) — see resume_process below.

        On resume, LangGraph re-runs this node function from the top;
        interrupt() is the first (and only) side-effecting statement here
        so that replay is harmless — everything above it is a plain read
        of already-checkpointed state, and everything below it (recording
        the decision) executes exactly once, on the resume pass.
        """
        proposed = state.get("proposed_action")
        action_id = state.get("pending_action_id")
        if not proposed or not action_id:
            return {"decision": None}

        decision = interrupt(
            {
                "type": "approval_request",
                "action_id": action_id,
                "tool": proposed["tool"],
                "method": proposed["method"],
                "description": proposed["description"],
                "payload": proposed["payload"],
            }
        )
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        state_store.resolve_pending_action(action_id, approved=approved)
        return {"decision": approved}

    def execute_node(state: GraphState) -> dict[str, Any]:
        process_id = state["process_id"]
        proposed = state.get("proposed_action")
        decision = state.get("decision")

        if not proposed or not decision:
            outcome = {"executed": False, "reason": "no_action_proposed" if not proposed else "rejected"}
            state_store.set_status(process_id, stage="done", result=outcome)
            return {"result": outcome}

        tool = tools[proposed["tool"]]
        method = getattr(tool, proposed["method"])
        action_result = method(process_id, dry_run=False, **proposed["payload"])
        outcome = {
            "executed": action_result.executed,
            "description": action_result.description,
            "details": action_result.details,
        }
        state_store.set_status(process_id, stage="done", result=outcome)
        return {"result": outcome}

    graph = StateGraph(GraphState)
    graph.add_node("fetch", fetch_node)
    graph.add_node("reason", reason_node)
    graph.add_node("propose", propose_node)
    graph.add_node("approval", approval_node)
    graph.add_node("execute", execute_node)

    graph.set_entry_point("fetch")
    graph.add_edge("fetch", "reason")
    graph.add_edge("reason", "propose")
    graph.add_edge("propose", "approval")
    graph.add_edge("approval", "execute")
    graph.add_edge("execute", END)

    return graph.compile(checkpointer=checkpointer)


def start_process(graph: Any, process_id: str, queries: dict[str, dict[str, Any]]) -> RunOutcome:
    """Run the graph from the start for one process. Returns a paused
    RunOutcome (pending_action set) if a proposal needs approval, or a
    finished one (final_result set) if the reasoner proposed nothing.
    """
    initial_state: GraphState = {"process_id": process_id, "queries": queries}
    result = graph.invoke(initial_state, config=_config(process_id))
    return _to_outcome(process_id, result)


def resume_process(graph: Any, process_id: str, approved: bool) -> RunOutcome:
    """Resume a paused graph with a human's Approve/Reject decision."""
    result = graph.invoke(Command(resume={"approved": approved}), config=_config(process_id))
    return _to_outcome(process_id, result)


def _to_outcome(process_id: str, result: dict[str, Any]) -> RunOutcome:
    if "__interrupt__" in result:
        return RunOutcome(
            process_id=process_id,
            summary=result.get("summary"),
            pending_action=result["__interrupt__"][0].value,
            final_result=None,
        )
    return RunOutcome(
        process_id=process_id,
        summary=result.get("summary"),
        pending_action=None,
        final_result=result.get("result"),
    )
