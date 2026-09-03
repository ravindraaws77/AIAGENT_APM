from apm.agent.reasoner import SYSTEM_PROMPT, parse_reasoning_response


def test_system_prompt_lists_excel_file_as_a_proposable_tool() -> None:
    """Regression guard for a real bug: SYSTEM_PROMPT's tool enum only
    listed "ms_excel" even after "excel_file" (src/apm/tools/excel_file_tool.py)
    became the one actually wired into apm.api.dependencies.get_graph --
    meaning the reasoner could never legally propose a write_range action
    against it. Caught by a real user request ("update order 223's status
    to Paid") that had nowhere to go. A plain string check because the
    thing that broke was the literal prompt text sent to Claude, not any
    parsing/validation code (parse_reasoning_response doesn't constrain
    "tool" at all -- see test_parse_response_with_excel_file_proposed_action).
    """
    assert '"excel_file"' in SYSTEM_PROMPT


def test_system_prompt_prioritizes_an_explicit_request_over_guessing() -> None:
    """Regression guard for the actual root cause behind the
    "update order 223's status to Paid" symptom: even after excel_file
    became a legal tool, ClaudeReasoner.reason() didn't accept a
    request_text argument at all, so the reasoner never saw what the
    user asked for -- only the fetched data -- and fell back to
    inventing its own idea of a helpful action (a payment-follow-up
    email) instead of doing what was actually requested. SYSTEM_PROMPT
    must instruct it to honor an explicit request over guessing.
    """
    assert "Propose the action that directly fulfills it" in SYSTEM_PROMPT


def test_parse_response_with_no_action() -> None:
    text = '{"summary": "All good.", "proposed_action": null}'

    result = parse_reasoning_response(text)

    assert result.summary == "All good."
    assert result.proposed_action is None
    assert result.category == "other"  # not present in the response -- defaults


def test_parse_response_with_category() -> None:
    text = '{"summary": "Order delayed.", "category": "shipment_delay", "proposed_action": null}'

    result = parse_reasoning_response(text)

    assert result.category == "shipment_delay"


def test_parse_response_with_proposed_action() -> None:
    text = """
    {
      "summary": "The shipment is delayed.",
      "proposed_action": {
        "tool": "gmail",
        "method": "send_email",
        "description": "Send a follow-up email about the delay",
        "payload": {"to": "customer@example.com", "subject": "Update", "body": "Sorry for the delay."}
      }
    }
    """

    result = parse_reasoning_response(text)

    assert result.summary == "The shipment is delayed."
    assert result.proposed_action is not None
    assert result.proposed_action.tool == "gmail"
    assert result.proposed_action.method == "send_email"
    assert result.proposed_action.payload["to"] == "customer@example.com"


def test_parse_response_with_excel_file_proposed_action() -> None:
    text = """
    {
      "summary": "Acme Corp's order is unpaid.",
      "proposed_action": {
        "tool": "excel_file",
        "method": "write_range",
        "description": "Mark order 223 as Paid in the tracker",
        "payload": {"sheet_name": "Orders", "address": "C5", "values": [["Paid"]]}
      }
    }
    """

    result = parse_reasoning_response(text)

    assert result.proposed_action.tool == "excel_file"
    assert result.proposed_action.method == "write_range"
    assert result.proposed_action.payload["address"] == "C5"


def test_parse_response_wrapped_in_markdown_code_fence() -> None:
    """Reproduces a real response observed from the live Anthropic API:
    despite SYSTEM_PROMPT saying "respond with ONLY a JSON object", the
    model wrapped it in a ```json fence anyway.
    """
    text = """```json
    {"summary": "All good.", "proposed_action": null}
    ```"""

    result = parse_reasoning_response(text)

    assert result.summary == "All good."
    assert result.proposed_action is None


def test_parse_response_wrapped_in_plain_code_fence() -> None:
    text = "```\n{\"summary\": \"All good.\", \"proposed_action\": null}\n```"

    result = parse_reasoning_response(text)

    assert result.summary == "All good."
