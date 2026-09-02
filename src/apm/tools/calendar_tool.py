"""Google Calendar connector — read/search only for this phase.

Same read-first pattern as gmail_tool.py: create/update events is
documented as a future capability in docs/capability-map.md, deferred to
phase 5 where the LangGraph human-approval interrupt exists to gate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from apm.config import Settings
from apm.state.store import StateStore
from apm.tools.base import BaseTool, Capability

CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


class CalendarClient(Protocol):
    """The minimal surface CalendarTool needs from a Calendar API client.
    Both the real client (`GoogleApiCalendarClient`, below) and test
    fakes implement just this.
    """

    def list_events(
        self, time_min: str | None, time_max: str | None, query: str | None, max_results: int
    ) -> list[dict[str, Any]]: ...

    def get_event(self, event_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class EventSummary:
    event_id: str
    title: str
    start: str | None
    end: str | None
    attendees: list[str]
    location: str | None


class CalendarTool(BaseTool):
    """Read-only Google Calendar connector: list/search events and read
    a single event's details.
    """

    name = "google_calendar"
    capabilities = frozenset({Capability.READ})

    def __init__(self, state: StateStore, client: CalendarClient) -> None:
        super().__init__(state)
        self._client = client

    def health_check(self) -> bool:
        try:
            self._client.list_events(time_min=None, time_max=None, query=None, max_results=1)
            return True
        except Exception:
            return False

    def search_events(
        self,
        process_id: str,
        query: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 10,
    ) -> list[EventSummary]:
        """List/search events, optionally filtered by a free-text query
        and/or an RFC3339 time window (e.g. `time_min="2026-09-01T00:00:00Z"`).
        """
        raw_events = self._client.list_events(
            time_min=time_min, time_max=time_max, query=query, max_results=max_results
        )
        summaries = [self._to_summary(e) for e in raw_events]
        self._log(
            process_id,
            "read",
            f"Searched Calendar (query={query!r}), found {len(summaries)} event(s)",
            {"query": query, "time_min": time_min, "time_max": time_max, "count": len(summaries)},
        )
        return summaries

    def read_event(self, process_id: str, event_id: str) -> EventSummary:
        summary = self._to_summary(self._client.get_event(event_id))
        self._log(
            process_id,
            "read",
            f"Read Calendar event '{summary.title}'",
            {"event_id": event_id},
        )
        return summary

    @staticmethod
    def _to_summary(raw: dict[str, Any]) -> EventSummary:
        start = raw.get("start", {})
        end = raw.get("end", {})
        return EventSummary(
            event_id=raw["id"],
            title=raw.get("summary", "(no title)"),
            start=start.get("dateTime") or start.get("date"),
            end=end.get("dateTime") or end.get("date"),
            attendees=[a.get("email", "") for a in raw.get("attendees", [])],
            location=raw.get("location"),
        )


class GoogleApiCalendarClient:
    """Real Calendar API client, built from OAuth credentials obtained via
    apm.tools.google_auth.load_credentials. Imports googleapiclient
    lazily so this module — and CalendarTool's unit tests, which use a
    fake client — don't require that dependency at import time.
    """

    def __init__(self, credentials: Any, calendar_id: str = "primary") -> None:
        from googleapiclient.discovery import build

        self._service = build("calendar", "v3", credentials=credentials)
        self._calendar_id = calendar_id

    def list_events(
        self, time_min: str | None, time_max: str | None, query: str | None, max_results: int
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "calendarId": self._calendar_id,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query
        response = self._service.events().list(**params).execute()
        return response.get("items", [])

    def get_event(self, event_id: str) -> dict[str, Any]:
        return self._service.events().get(calendarId=self._calendar_id, eventId=event_id).execute()


def build_calendar_tool(state: StateStore, settings: Settings) -> CalendarTool:
    """Convenience factory: runs the OAuth flow (if needed) and returns a
    CalendarTool backed by the real Calendar API. Shares the same token
    cache as build_gmail_tool if both scopes are requested together —
    see apm.tools.google_auth.
    """
    from apm.tools.google_auth import load_credentials

    credentials = load_credentials(settings, scopes=[CALENDAR_READONLY_SCOPE])
    return CalendarTool(state, GoogleApiCalendarClient(credentials))
