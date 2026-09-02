from apm.ui.logic import build_start_request, format_pending_action, format_result


def test_build_start_request_both_queries() -> None:
    body = build_start_request("newer_than:30d", "renewal")
    assert body == {"gmail_query": "newer_than:30d", "calendar_query": "renewal"}


def test_build_start_request_trims_whitespace() -> None:
    body = build_start_request("  newer_than:30d  ", "  ")
    assert body == {"gmail_query": "newer_than:30d"}


def test_build_start_request_empty_when_both_blank() -> None:
    assert build_start_request("", "   ") == {}


def test_format_pending_action() -> None:
    action = {"tool": "gmail", "method": "send_email", "description": "Send a follow-up email"}
    assert format_pending_action(action) == "gmail.send_email: Send a follow-up email"


def test_format_result_none() -> None:
    assert format_result(None) == ""


def test_format_result_no_action_proposed() -> None:
    assert format_result({"executed": False, "reason": "no_action_proposed"}) == "No action was needed."


def test_format_result_rejected() -> None:
    result = format_result({"executed": False, "reason": "rejected"})
    assert result == "Action was rejected — nothing was sent or changed."


def test_format_result_executed() -> None:
    result = format_result({"executed": True, "description": "Send email to c@example.com: 'Update'"})
    assert result == "Done: Send email to c@example.com: 'Update'"
