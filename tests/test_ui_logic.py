from apm.ui.logic import (
    build_query_request,
    category_color,
    format_action_details,
    format_category_label,
    format_pending_action,
    format_result,
    normalize_pending_action,
    order_status,
    prepare_history_rows,
    prepare_order_rows,
)


def test_build_query_request_returns_body() -> None:
    assert build_query_request("chase up order 4521") == {"text": "chase up order 4521"}


def test_build_query_request_trims_whitespace() -> None:
    assert build_query_request("  check the Acme renewal  ") == {"text": "check the Acme renewal"}


def test_build_query_request_none_when_blank() -> None:
    assert build_query_request("   ") is None


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


def test_category_color_curated_categories_are_stable() -> None:
    assert category_color("shipment_delay") == "red"
    assert category_color("renewal_reminder") == "blue"
    assert category_color("other") == "grey"


def test_category_color_unknown_category_is_deterministic() -> None:
    """The exact color for a novel category doesn't matter, but it must
    be the SAME color every call (and, implicitly, every app restart --
    this is why the implementation avoids Python's salted hash())."""
    first = category_color("some_new_thing_the_model_invented")
    second = category_color("some_new_thing_the_model_invented")
    assert first == second


def test_category_color_different_unknown_categories_can_differ() -> None:
    colors = {category_color(f"category_{i}") for i in range(6)}
    assert len(colors) > 1  # not every unknown category collides onto the same color


def test_format_category_label() -> None:
    assert format_category_label("shipment_delay") == "Shipment Delay"
    assert format_category_label("other") == "Other"


def test_prepare_history_rows_flattens_category_from_details() -> None:
    rows = [
        {
            "id": "e1",
            "timestamp": "2026-09-10T00:00:00Z",
            "tool": "gmail",
            "event_type": "action_proposed",
            "summary": "Proposed a follow-up",
            "details": {"category": "shipment_delay", "to": "c@realcorp.io"},
        }
    ]

    prepared = prepare_history_rows(rows)

    assert prepared[0]["category"] == "Shipment Delay"
    assert prepared[0]["category_color"] == "red"
    assert prepared[0]["id"] == "e1"  # original fields preserved


def test_prepare_history_rows_handles_missing_category() -> None:
    rows = [
        {
            "id": "e2",
            "timestamp": "2026-09-10T00:00:00Z",
            "tool": "gmail",
            "event_type": "read",
            "summary": "Searched Gmail",
            "details": {"query": "order"},
        }
    ]

    prepared = prepare_history_rows(rows)

    assert prepared[0]["category"] == ""
    assert prepared[0]["category_color"] == ""


def test_order_status_summarized_is_needs_approval() -> None:
    assert order_status({"stage": "summarized"}) == ("Needs approval", "amber")


def test_order_status_done_and_executed() -> None:
    process = {"stage": "done", "result": {"executed": True, "description": "Sent"}}
    assert order_status(process) == ("Done", "green")


def test_order_status_done_and_rejected() -> None:
    process = {"stage": "done", "result": {"executed": False, "reason": "rejected"}}
    assert order_status(process) == ("Rejected", "red")


def test_order_status_done_no_action_needed() -> None:
    process = {"stage": "done", "result": {"executed": False, "reason": "no_action_proposed"}}
    assert order_status(process) == ("No action needed", "grey")


def test_order_status_in_progress_for_earlier_stages() -> None:
    assert order_status({"stage": "fetched"}) == ("In progress", "blue")
    assert order_status({}) == ("In progress", "blue")


def test_prepare_order_rows_builds_display_fields() -> None:
    processes = [
        {
            "process_id": "order-4521",
            "stage": "summarized",
            "category": "shipment_delay",
            "summary": "Shipment is delayed.",
            "updated_at": "2026-09-10T00:00:00Z",
        }
    ]

    rows = prepare_order_rows(processes)

    assert rows == [
        {
            "process_id": "order-4521",
            "category": "Shipment Delay",
            "category_color": "red",
            "status_label": "Needs approval",
            "status_color": "amber",
            "summary": "Shipment is delayed.",
            "updated_at": "2026-09-10T00:00:00Z",
        }
    ]


def test_prepare_order_rows_handles_missing_category_and_summary() -> None:
    processes = [{"process_id": "order-1", "stage": "fetched", "updated_at": "2026-09-10T00:00:00Z"}]

    rows = prepare_order_rows(processes)

    assert rows[0]["category"] == ""
    assert rows[0]["category_color"] == ""
    assert rows[0]["summary"] == ""


def test_prepare_order_rows_sorts_most_recently_updated_first() -> None:
    processes = [
        {"process_id": "older", "stage": "done", "updated_at": "2026-09-01T00:00:00Z"},
        {"process_id": "newer", "stage": "done", "updated_at": "2026-09-10T00:00:00Z"},
    ]

    rows = prepare_order_rows(processes)

    assert [row["process_id"] for row in rows] == ["newer", "older"]


def test_normalize_pending_action_flattens_nested_payload() -> None:
    """apm.state.store.StateStore.add_pending_action stores the *entire*
    proposed-action dict (tool/method/description/payload) under the
    record's own "payload" key -- reproduces that exact shape, as
    returned by GET /processes/{id}/pending.
    """
    record = {
        "id": "action-1",
        "process_id": "order-1",
        "tool": "gmail",
        "description": "Send a follow-up email about the delay",
        "payload": {
            "tool": "gmail",
            "method": "send_email",
            "description": "Send a follow-up email about the delay",
            "payload": {"to": "c@realcorp.io", "subject": "Update", "body": "Sorry for the delay."},
        },
        "category": "shipment_delay",
        "status": "pending",
    }

    action = normalize_pending_action(record)

    assert action == {
        "tool": "gmail",
        "method": "send_email",
        "description": "Send a follow-up email about the delay",
        "payload": {"to": "c@realcorp.io", "subject": "Update", "body": "Sorry for the delay."},
        "category": "shipment_delay",
    }
