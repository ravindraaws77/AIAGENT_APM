import pytest

from apm.agent.intent import parse_intent_response


def test_parse_intent_with_gmail_and_calendar_query() -> None:
    text = """
    {
      "process_id": "order-4521",
      "gmail_query": "order 4521",
      "calendar_query": "order 4521"
    }
    """

    result = parse_intent_response(text)

    assert result.process_id == "order-4521"
    assert result.gmail_query == "order 4521"
    assert result.calendar_query == "order 4521"


def test_parse_intent_with_only_gmail_query() -> None:
    text = '{"process_id": "acme-renewal", "gmail_query": "from:acme.com", "calendar_query": null}'

    result = parse_intent_response(text)

    assert result.gmail_query == "from:acme.com"
    assert result.calendar_query is None


def test_parse_intent_with_only_calendar_query() -> None:
    text = '{"process_id": "acme-renewal", "gmail_query": null, "calendar_query": "renewal"}'

    result = parse_intent_response(text)

    assert result.gmail_query is None
    assert result.calendar_query == "renewal"


def test_parse_intent_requires_at_least_one_query() -> None:
    text = '{"process_id": "order-4521", "gmail_query": null, "calendar_query": null}'

    with pytest.raises(ValueError):
        parse_intent_response(text)


def test_parse_intent_wrapped_in_markdown_code_fence() -> None:
    """Same markdown-fence habit test_reasoner.py reproduces for the
    reasoner's Claude responses -- the intent parser hits the same model
    behavior, so it needs the same tolerance.
    """
    text = """```json
    {"process_id": "order-4521", "gmail_query": "order 4521", "calendar_query": null}
    ```"""

    result = parse_intent_response(text)

    assert result.process_id == "order-4521"
