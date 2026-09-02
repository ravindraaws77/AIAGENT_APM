"""FastAPI dependency providers.

Both are cached (built once per running process, not per-request) since
the compiled graph's checkpointer holds the agent's paused/in-progress
state in memory for the lifetime of the server process — a fresh graph
per request would lose that state between the "start" and "decision"
calls for the same process_id.

Tests override both via `app.dependency_overrides` with a graph/store
built from fake tools and a fake reasoner (see tests/test_api.py) — real
credentials are only needed to actually run the server, never to test it.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.memory import MemorySaver

from apm.agent.graph import build_graph
from apm.agent.reasoner import ClaudeReasoner
from apm.config import load_settings
from apm.state.store import StateStore
from apm.tools.google_auth import build_gmail_and_calendar_tools


@lru_cache
def get_state_store() -> StateStore:
    return StateStore()


@lru_cache
def get_graph():
    settings = load_settings()
    state = get_state_store()
    gmail_tool, calendar_tool = build_gmail_and_calendar_tools(state, settings)
    tools = {"gmail": gmail_tool, "google_calendar": calendar_tool}
    reasoner = ClaudeReasoner(settings)
    return build_graph(tools, reasoner, state, checkpointer=MemorySaver())
