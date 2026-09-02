from apm.agent.reasoner import parse_reasoning_response


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
