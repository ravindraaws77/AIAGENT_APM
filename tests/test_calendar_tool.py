from pathlib import Path
from typing import Any

from apm.state.store import StateStore
from apm.tools.base import Capability
from apm.tools.calendar_tool import CalendarTool


class FakeCalendarClient:
    """Implements the CalendarClient protocol in-memory — no network, no
    credentials — so CalendarTool's logic can be unit tested directly.
    """

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = {e["id"]: e for e in events}

    def list_events(
        self, time_min: str | None, time_max: str | None, query: str | None, max_results: int
    ) -> list[dict[str, Any]]:
        return list(self._events.values())[:max_results]

    def get_event(self, event_id: str) -> dict[str, Any]:
        return self._events[event_id]


class BrokenCalendarClient:
    def list_events(self, time_min, time_max, query, max_results):
        raise RuntimeError("simulated API failure")

    def get_event(self, event_id: str) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")


def _raw_event(
    event_id: str, title: str, start: str, end: str, attendees: list[str], location: str | None = None
) -> dict[str, Any]:
    return {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "attendees": [{"email": a} for a in attendees],
        "location": location,
    }


def test_calendar_tool_is_read_only() -> None:
    assert CalendarTool.capabilities == frozenset({Capability.READ})


def test_search_events_returns_summaries_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeCalendarClient(
        [
            _raw_event(
                "e1",
                "Renewal review call",
                "2026-09-10T15:00:00Z",
                "2026-09-10T15:30:00Z",
                ["customer@example.com"],
                location="Google Meet",
            )
        ]
    )
    tool = CalendarTool(store, client)

    results = tool.search_events("order-123", query="renewal", max_results=5)

    assert len(results) == 1
    assert results[0].event_id == "e1"
    assert results[0].title == "Renewal review call"
    assert results[0].attendees == ["customer@example.com"]
    assert results[0].location == "Google Meet"

    events = store.list_events("order-123")
    assert any(e["event_type"] == "read" and e["details"]["query"] == "renewal" for e in events)


def test_read_event(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeCalendarClient(
        [_raw_event("e1", "Kickoff", "2026-09-05T09:00:00Z", "2026-09-05T09:30:00Z", [])]
    )
    tool = CalendarTool(store, client)

    summary = tool.read_event("order-1", "e1")

    assert summary.event_id == "e1"
    assert summary.title == "Kickoff"


def test_missing_fields_fall_back_to_defaults(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeCalendarClient([{"id": "e2"}])
    tool = CalendarTool(store, client)

    summary = tool.read_event("order-1", "e2")

    assert summary.title == "(no title)"
    assert summary.start is None
    assert summary.end is None
    assert summary.attendees == []
    assert summary.location is None


def test_all_day_event_uses_date_field(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeCalendarClient(
        [{"id": "e3", "summary": "All-day reminder", "start": {"date": "2026-09-20"}, "end": {"date": "2026-09-21"}}]
    )
    tool = CalendarTool(store, client)

    summary = tool.read_event("order-1", "e3")

    assert summary.start == "2026-09-20"
    assert summary.end == "2026-09-21"


def test_health_check_true(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = CalendarTool(store, FakeCalendarClient([]))
    assert tool.health_check() is True


def test_health_check_false_on_client_error(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = CalendarTool(store, BrokenCalendarClient())
    assert tool.health_check() is False
