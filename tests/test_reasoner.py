from apm.agent.reasoner import parse_reasoning_response


def test_parse_response_with_no_action() -> None:
    text = '{"summary": "All good.", "proposed_action": null}'

    result = parse_reasoning_response(text)

    assert result.summary == "All good."
    assert result.proposed_action is None


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
