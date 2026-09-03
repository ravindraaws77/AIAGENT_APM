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
    tool: str  # "gmail" | "google_calendar" | "ms_excel" | "excel_file"
    method: str  # e.g. "send_email", "create_event", "write_range"
    description: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ReasoningResult:
    summary: str
    proposed_action: ProposedAction | None
    category: str = "other"


class Reasoner(Protocol):
    def reason(
        self, process_id: str, context: dict[str, Any], request_text: str | None = None
    ) -> ReasoningResult: ...


SYSTEM_PROMPT = """You are the reasoning layer of APM (Agentic Process \
Management), an orchestration agent that helps a person run a business \
process (e.g. order-to-renewal) across email, calendar, and spreadsheet \
tools, without them having to operate each tool by hand.

You will be given the data the agent has just read from those tools for \
one process, and — when the person typed a specific free-text request \
rather than just asking to check on something — that request verbatim. \
Do two things:

1. Write a short, plain-language summary of the current state for a \
business user — no jargon, 2-4 sentences.

2. Propose exactly ONE next action if one is warranted; propose none if \
not. Two cases:
   - A request was given: it tells you the goal. Propose the action \
that directly fulfills it (e.g. "update order 223's status to Paid" -> \
propose write_range setting that order's status cell to "Paid"), not a \
different action you independently think would help more, as long as \
you can support every value it needs from the fetched data (see the \
"never invent" rule below). If the fetched data can't support the \
request at all (e.g. it asks to update a workbook but no spreadsheet \
was fetched, or asks to update an order that isn't in the fetched data), \
propose nothing and say exactly what's missing in the summary — do not \
substitute a different action instead of what was actually asked for.
   - No request was given (e.g. a plain "check on order 4521"): infer \
whatever concrete next action would genuinely help from the fetched \
data alone (e.g. a follow-up email about a delay, a reminder event for \
a renewal call, logging a row in a tracker). If nothing useful needs to \
happen right now, propose none — do not invent busywork.

Never invent contact details. Every value in a proposed action's payload \
— an email address, a name, a date, an attendee — must come from the \
fetched data you were given. If an action would genuinely help but you \
cannot find a real value for something it needs (e.g. no customer email \
address appears anywhere in the fetched data), do not propose that \
action. Instead, say so plainly in the summary (e.g. "a follow-up email \
seems warranted, but no customer email address was found in the fetched \
data") so a person knows what's missing rather than being shown a \
fabricated placeholder.

Also classify the underlying situation with a short, stable, snake_case \
category slug — this is what lets a person spot a recurring pattern \
across different processes (e.g. three separate orders all delayed by \
the same supplier issue) and address the root cause, instead of \
handling each case as if it were unrelated. Reuse the exact same slug \
for the same kind of situation every time; do not invent a new wording \
for something you've already categorized before. Prefer one of these \
when it genuinely fits: "shipment_delay", "renewal_reminder", \
"missing_information", "customer_inquiry", "payment_issue". Use "other" \
only when none of those — or an equally short, clear slug of your own — \
actually describes it.

The fetched data you're given is a dict keyed by tool name — "gmail", \
"google_calendar", and, if a spreadsheet is connected, either "ms_excel" \
or "excel_file" (never both). If you propose a write_range action, set \
"tool" to whichever of those two keys the spreadsheet data actually \
appeared under — do not guess or default to one; use the exact key you \
saw in the fetched data.

Respond with ONLY a JSON object of this exact shape, no other text before \
or after it:
{
  "summary": "...",
  "category": "shipment_delay" | "renewal_reminder" | "missing_information" | "customer_inquiry" | "payment_issue" | "other" | "<your own short snake_case slug>",
  "proposed_action": {
    "tool": "gmail" | "google_calendar" | "ms_excel" | "excel_file",
    "method": "send_email" | "create_event" | "write_range",
    "description": "one sentence describing the action for a human approver",
    "payload": { ... arguments that tool method needs, matching its signature ... }
  } | null
}

Payload shapes:
- send_email: {"to": str, "subject": str, "body": str}
- create_event: {"title": str, "start": RFC3339 str, "end": RFC3339 str, "attendees": [str], "location": str | null}
- write_range: {"sheet_name": str, "address": str, "values": [[cell, ...], ...]} — "address" \
is the cell or range you're overwriting (e.g. "C5" for one cell, "C5:D5" \
for a row), found by matching a real row/column in the fetched \
spreadsheet data (e.g. an order id in one column identifies the row; a \
header like "Status" identifies the column) — never invent a cell \
address that doesn't correspond to something you can see in the fetched \
data. "values" is a list of rows shaped to match "address" (one cell, \
one value: [["Paid"]]).
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

    def reason(self, process_id: str, context: dict[str, Any], request_text: str | None = None) -> ReasoningResult:
        import anthropic

        request_section = f"User's request: {request_text}\n\n" if request_text else ""
        client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Process id: {process_id}\n\n{request_section}Fetched data:\n"
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
    data = json.loads(strip_code_fence(text.strip()))
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
    category = data.get("category") or "other"
    return ReasoningResult(summary=data["summary"], proposed_action=proposed_action, category=category)


def strip_code_fence(text: str) -> str:
    """Remove a wrapping ```json / ``` fence, if present. Leaves
    unfenced text untouched. Public (not just for this module) since
    apm.agent.intent's ClaudeIntentParser hits the same markdown-fence
    habit from Claude and reuses this rather than duplicating it.
    """
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]  # drop the opening ``` or ```json line
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
