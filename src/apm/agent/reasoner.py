"""The reasoning step: turns fetched tool data into a plain-language
summary and, at most, one proposed next action. This is the
"Intelligence / Conversation" layer (layer 3) from docs/architecture.md.

Kept behind a Reasoner protocol, same spirit as the tool connectors in
apm.tools, so the graph's control flow (apm.agent.graph) can be tested
with a fake reasoner and no Anthropic API key. See tests/test_agent_graph.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from apm.config import Settings

DEFAULT_MODEL = "claude-sonnet-5"


@dataclass(frozen=True)
class ProposedAction:
    tool: str  # "gmail" | "google_calendar" | "ms_excel"
    method: str  # e.g. "send_email", "create_event", "write_range"
    description: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ReasoningResult:
    summary: str
    proposed_action: ProposedAction | None


class Reasoner(Protocol):
    def reason(self, process_id: str, context: dict[str, Any]) -> ReasoningResult: ...


SYSTEM_PROMPT = """You are the reasoning layer of APM (Agentic Process \
Management), an orchestration agent that helps a person run a business \
process (e.g. order-to-renewal) across email, calendar, and spreadsheet \
tools, without them having to operate each tool by hand.

You will be given the data the agent has just read from those tools for \
one process. Do two things:

1. Write a short, plain-language summary of the current state for a \
business user — no jargon, 2-4 sentences.

2. If, and only if, a concrete next action would genuinely help (e.g. a \
follow-up email about a delay, a reminder event for a renewal call, \
logging a row in a tracker), propose exactly ONE action. If nothing \
useful needs to happen right now, propose none — do not invent busywork.

Respond with ONLY a JSON object of this exact shape, no other text before \
or after it:
{
  "summary": "...",
  "proposed_action": {
    "tool": "gmail" | "google_calendar" | "ms_excel",
    "method": "send_email" | "create_event" | "write_range",
    "description": "one sentence describing the action for a human approver",
    "payload": { ... arguments that tool method needs, matching its signature ... }
  } | null
}

Payload shapes:
- send_email: {"to": str, "subject": str, "body": str}
- create_event: {"title": str, "start": RFC3339 str, "end": RFC3339 str, "attendees": [str], "location": str | null}
- write_range: {"sheet_name": str, "address": str, "values": [[cell, ...], ...]}
"""


class ClaudeReasoner:
    """Real reasoner backed by the Anthropic Messages API. Imports the
    anthropic SDK lazily so it isn't a hard dependency for graph-logic
    tests, which use a fake reasoner instead.
    """

    def __init__(self, settings: Settings, model: str | None = None) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. See .env.example.")
        self._settings = settings
        self._model = model or settings.anthropic_model or DEFAULT_MODEL

    def reason(self, process_id: str, context: dict[str, Any]) -> ReasoningResult:
        import anthropic

        client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Process id: {process_id}\n\nFetched data:\n"
                        f"{json.dumps(context, indent=2, default=str)}"
                    ),
                }
            ],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            block_types = [block.type for block in response.content]
            raise RuntimeError(
                "Claude returned no text content to parse "
                f"(stop_reason={response.stop_reason!r}, content block types={block_types!r}). "
                "This can happen if max_tokens is too small for the model to finish responding."
            )
        return parse_reasoning_response(text)


def parse_reasoning_response(text: str) -> ReasoningResult:
    """Parse the JSON contract described in SYSTEM_PROMPT. Split out from
    ClaudeReasoner so it's independently testable against hand-written
    sample responses without any API call.

    Tolerates the model wrapping its answer in a markdown code fence
    (```json ... ``` or ``` ... ```) despite SYSTEM_PROMPT telling it not
    to — a common enough LLM habit in practice (confirmed against a real
    Claude call) that it's cheaper to strip defensively than to rely on
    prompting alone.
    """
    data = json.loads(_strip_code_fence(text.strip()))
    action_data = data.get("proposed_action")
    proposed_action = (
        ProposedAction(
            tool=action_data["tool"],
            method=action_data["method"],
            description=action_data["description"],
            payload=action_data.get("payload", {}),
        )
        if action_data
        else None
    )
    return ReasoningResult(summary=data["summary"], proposed_action=proposed_action)


def _strip_code_fence(text: str) -> str:
    """Remove a wrapping ```json / ``` fence, if present. Leaves
    unfenced text untouched.
    """
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]  # drop the opening ``` or ```json line
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
