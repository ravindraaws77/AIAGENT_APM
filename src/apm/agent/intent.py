"""Free-text intent parsing: turns a business user's plain-language
request ("chase up order 4521", "check on the Acme renewal") into the
process id + Gmail/Calendar queries apm.agent.graph.start_process already
knows how to run. This is what lets the dashboard offer a single free-text
box instead of asking a person to invent a process id and know Gmail
search syntax by hand.

Kept behind an IntentParser protocol, same pattern as
apm.agent.reasoner.Reasoner, so the API route can be tested with a fake
parser and no Anthropic API key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from apm.agent.reasoner import strip_code_fence
from apm.config import Settings

DEFAULT_MODEL = "claude-sonnet-5"


@dataclass(frozen=True)
class ParsedIntent:
    process_id: str
    gmail_query: str | None = None
    calendar_query: str | None = None


class IntentParser(Protocol):
    def parse(self, text: str, known_process_ids: list[str]) -> ParsedIntent: ...


SYSTEM_PROMPT = """You turn a business user's free-text request into the \
structured input APM's agent needs to look into it: a process id plus a \
Gmail search query and/or a Calendar search query.

You will be given the request text and a list of process ids already in \
use (each one identifies an order/case/deal APM has looked into before).

1. Choose process_id:
   - If the request clearly continues or refers to one of the known \
process ids (the same order number, customer, or a natural rephrasing of \
one already in the list), reuse that exact id verbatim.
   - Otherwise invent a short, stable, kebab-case id from a concrete \
identifier in the request — an order number ("order 4521" -> \
"order-4521"), a customer/company name ("the Acme renewal" -> \
"acme-renewal"). If there is truly no identifying detail, use a short \
kebab-case slug for the topic instead (e.g. "shipment-delays").

2. Choose gmail_query: Gmail search syntax (e.g. "from:acme.com", \
"subject:renewal", "newer_than:30d", or plain keywords) that would find \
the emails relevant to this request. Set it to null if email isn't \
relevant to the request.

3. Choose calendar_query: plain keyword text (not Gmail syntax) that \
would find the calendar events relevant to this request, e.g. "renewal" \
or "Acme". Set it to null if calendar isn't relevant to the request.

At least one of gmail_query / calendar_query must be non-null — pick \
whichever tool(s) the request is actually about; use both if the request \
plausibly needs both.

Respond with ONLY a JSON object of this exact shape, no other text before \
or after it:
{
  "process_id": "...",
  "gmail_query": "..." | null,
  "calendar_query": "..." | null
}
"""


class ClaudeIntentParser:
    """Real parser backed by the Anthropic Messages API. Imports the
    anthropic SDK lazily so it isn't a hard dependency for tests, which
    use a fake parser instead.
    """

    def __init__(self, settings: Settings, model: str | None = None) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. See .env.example.")
        self._settings = settings
        self._model = model or settings.anthropic_model or DEFAULT_MODEL

    def parse(self, text: str, known_process_ids: list[str]) -> ParsedIntent:
        import anthropic

        client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Known process ids already in use: {json.dumps(known_process_ids)}\n\n"
                        f"User request:\n{text}"
                    ),
                }
            ],
        )
        content_text = "".join(block.text for block in response.content if block.type == "text")
        if not content_text.strip():
            block_types = [block.type for block in response.content]
            raise RuntimeError(
                "Claude returned no text content to parse "
                f"(stop_reason={response.stop_reason!r}, content block types={block_types!r})."
            )
        return parse_intent_response(content_text)


def parse_intent_response(text: str) -> ParsedIntent:
    """Parse the JSON contract described in SYSTEM_PROMPT. Split out from
    ClaudeIntentParser so it's independently testable against hand-written
    sample responses without any API call.
    """
    data = json.loads(strip_code_fence(text.strip()))
    gmail_query = data.get("gmail_query") or None
    calendar_query = data.get("calendar_query") or None
    if gmail_query is None and calendar_query is None:
        raise ValueError("intent parsing produced neither a gmail_query nor a calendar_query")
    return ParsedIntent(process_id=data["process_id"], gmail_query=gmail_query, calendar_query=calendar_query)
