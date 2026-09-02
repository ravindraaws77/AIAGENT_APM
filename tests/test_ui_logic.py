from apm.ui.logic import build_start_request, format_action_details, format_pending_action, format_result


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


def test_format_action_details_send_email() -> None:
    action = {
        "tool": "gmail",
        "method": "send_email",
        "payload": {"to": "c@realcorp.io", "subject": "Update", "body": "Line one.\n\nLine two."},
    }

    details = format_action_details(action)

    assert details == [
        ("To", "c@realcorp.io"),
        ("Subject", "Update"),
        ("Body", "Line one.\n\nLine two."),
    ]


def test_format_action_details_create_event_with_attendees_and_location() -> None:
    action = {
        "tool": "google_calendar",
        "method": "create_event",
        "payload": {
            "title": "Renewal call",
            "start": "2026-09-10T15:00:00Z",
            "end": "2026-09-10T15:30:00Z",
            "attendees": ["a@realcorp.io", "b@realcorp.io"],
            "location": "Google Meet",
        },
    }

    details = format_action_details(action)

    assert details == [
        ("Title", "Renewal call"),
        ("Start", "2026-09-10T15:00:00Z"),
        ("End", "2026-09-10T15:30:00Z"),
        ("Attendees", "a@realcorp.io, b@realcorp.io"),
        ("Location", "Google Meet"),
    ]


def test_format_action_details_create_event_without_attendees_or_location() -> None:
    action = {
        "tool": "google_calendar",
        "method": "create_event",
        "payload": {"title": "Kickoff", "start": "2026-09-05T09:00:00Z", "end": "2026-09-05T09:30:00Z"},
    }

    details = format_action_details(action)

    assert details == [
        ("Title", "Kickoff"),
        ("Start", "2026-09-05T09:00:00Z"),
        ("End", "2026-09-05T09:30:00Z"),
    ]


def test_format_action_details_write_range() -> None:
    action = {
        "tool": "ms_excel",
        "method": "write_range",
        "payload": {"sheet_name": "Renewals", "address": "A2:B2", "values": [["Acme", "2026-11-01"]]},
    }

    details = format_action_details(action)

    assert details == [
        ("Sheet", "Renewals"),
        ("Range", "A2:B2"),
        ("Rows", "1"),
    ]


def test_format_action_details_unknown_method_falls_back_to_raw_payload() -> None:
    action = {"tool": "mystery", "method": "do_something_new", "payload": {"foo": "bar"}}

    assert format_action_details(action) == [("foo", "bar")]
