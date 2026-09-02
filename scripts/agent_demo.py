"""End-to-end smoke-test for the full agent: fetch -> summarize -> propose
-> human approval (typed at this terminal) -> execute -> persist. This is
the whole MVP flow from docs/architecture.md, run for real.

Needs:
  - ANTHROPIC_API_KEY in .env (the reasoning step)
  - Google OAuth set up per scripts/gmail_demo.py / calendar_demo.py
    (this script uses both tools together, via build_gmail_and_calendar_tools
    so one consent covers both scopes)

Usage:
  python scripts/agent_demo.py order-123 --gmail-query "newer_than:30d"
  python scripts/agent_demo.py order-123 --calendar-query "renewal"

Nothing is sent/created until you type "y" at the approval prompt.
"""

from __future__ import annotations

import argparse

from langgraph.checkpoint.memory import MemorySaver

from apm.agent.graph import build_graph, resume_process, start_process
from apm.agent.reasoner import ClaudeReasoner
from apm.config import load_settings
from apm.state.store import StateStore
from apm.tools.google_auth import build_gmail_and_calendar_tools


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("process_id", help="An identifier for this process/case, e.g. an order id")
    parser.add_argument("--gmail-query", default=None, help="Gmail search query to fetch, e.g. 'newer_than:30d'")
    parser.add_argument("--calendar-query", default=None, help="Calendar search query to fetch")
    args = parser.parse_args()

    settings = load_settings()
    store = StateStore()
    gmail_tool, calendar_tool = build_gmail_and_calendar_tools(store, settings)
    tools = {"gmail": gmail_tool, "google_calendar": calendar_tool}
    reasoner = ClaudeReasoner(settings)

    graph = build_graph(tools, reasoner, store, checkpointer=MemorySaver())

    queries: dict[str, dict[str, object]] = {}
    if args.gmail_query is not None:
        queries["gmail"] = {"query": args.gmail_query, "max_results": 5}
    if args.calendar_query is not None:
        queries["google_calendar"] = {"query": args.calendar_query, "max_results": 5}

    if not queries:
        parser.error("pass at least one of --gmail-query / --calendar-query")

    outcome = start_process(graph, args.process_id, queries)
    print(f"\nSummary: {outcome.summary}\n")

    if outcome.pending_action:
        action = outcome.pending_action
        print(f"Proposed action ({action['tool']}.{action['method']}): {action['description']}")
        print(f"Details: {action['payload']}\n")
        answer = input("Approve this action? [y/N] ").strip().lower()
        outcome = resume_process(graph, args.process_id, approved=(answer == "y"))
        print(f"\nResult: {outcome.final_result}")
    else:
        print(f"No action proposed. Result: {outcome.final_result}")


if __name__ == "__main__":
    main()
