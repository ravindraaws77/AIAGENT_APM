"""FastAPI dependency providers.

All cached (built once per running process, not per-request) since a
compiled graph's checkpointer holds paused/in-progress state in memory
for the lifetime of the server process — a fresh graph per request would
lose that state between the "start" and "decision" calls for the same
process_id.

Tests override these via `app.dependency_overrides` with a graph/store
built from fake tools and a fake reasoner (see tests/test_api.py) — real
credentials are only needed to actually run the server, never to test it.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.memory import MemorySaver

from apm.agent.graph import build_action_graph, build_graph
from apm.agent.intent import ClaudeIntentParser
from apm.agent.reasoner import ClaudeReasoner
from apm.config import load_settings
from apm.state.store import StateStore
from apm.tools.base import BaseTool
from apm.tools.excel_file_tool import build_configured_excel_tool
from apm.tools.google_auth import build_configured_gmail_and_calendar_tools


@lru_cache
def get_state_store() -> StateStore:
    return StateStore()


@lru_cache
def get_tools() -> dict[str, BaseTool]:
    """The integration layer's tool connectors, shared by the reasoning
    graph (get_graph) and the tools-only action graph (get_action_graph),
    and by the /tools/* read routes -- one set of connectors, built once,
    regardless of which access path a caller uses.

    Each tool is only added when its credentials are actually configured
    (same "unconfigured -> absent, not a crash" rule for all three, not
    just Excel): a server with no Google OAuth client set up still
    serves Excel-only /tools/* traffic, and apm.api.tools_routes'
    _tool() already 503s cleanly on whichever tool key is missing.
    """
    settings = load_settings()
    state = get_state_store()
    tools: dict[str, BaseTool] = {}
    gmail_tool, calendar_tool = build_configured_gmail_and_calendar_tools(state, settings)
    if gmail_tool is not None:
        tools["gmail"] = gmail_tool
    if calendar_tool is not None:
        tools["google_calendar"] = calendar_tool
    excel_tool = build_configured_excel_tool(state, settings)
    if excel_tool is not None:
        tools["excel_file"] = excel_tool
    return tools


@lru_cache
def get_graph():
    settings = load_settings()
    reasoner = ClaudeReasoner(settings)
    return build_graph(get_tools(), reasoner, get_state_store(), checkpointer=MemorySaver())


@lru_cache
def get_action_graph():
    """The tools-only graph (propose -> approval -> execute, no fetch/
    reason, no Anthropic dependency) that apm.api.app's /tools/* write
    routes drive -- for an action a caller outside this repo's own
    reasoner has already decided on. A separate MemorySaver instance
    from get_graph's: a process id started here must be resumed here,
    never against get_graph's graph (see build_action_graph's
    docstring) -- keeping the checkpointers apart makes that mistake
    fail loudly (unknown thread_id) rather than silently.
    """
    return build_action_graph(get_tools(), get_state_store(), checkpointer=MemorySaver())


@lru_cache
def get_intent_parser():
    return ClaudeIntentParser(load_settings())
