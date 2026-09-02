"""Gmail connector — read/search only for this phase.

Per the tool-integration skill's "read first" rule, sending, drafting, and
labeling are deliberately *not* implemented here even though they're
documented as a future capability in docs/capability-map.md. They will be
added once the human-approval interrupt exists (phase 5), so a send call
is never reachable without that gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from apm.config import Settings
from apm.state.store import StateStore
from apm.tools.base import BaseTool, Capability

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class GmailClient(Protocol):
    """The minimal surface GmailTool needs from a Gmail API client. Both
    the real client (`GoogleApiGmailClient`, below) and test fakes
    implement just this, so the connector's logic can be tested without
    live credentials.
    """

    def list_message_ids(self, query: str, max_results: int) -> list[str]: ...

    def get_message(self, message_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class EmailSummary:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    received_at: str | None


class GmailTool(BaseTool):
    """Read-only Gmail connector: search and read message content/metadata."""

    name = "gmail"
    capabilities = frozenset({Capability.READ})

    def __init__(self, state: StateStore, client: GmailClient) -> None:
        super().__init__(state)
        self._client = client

    def health_check(self) -> bool:
        try:
            self._client.list_message_ids(query="", max_results=1)
            return True
        except Exception:
            return False

    def search_emails(
        self, process_id: str, query: str, max_results: int = 10
    ) -> list[EmailSummary]:
        """Search the mailbox using Gmail's query syntax (e.g.
        `"from:customer@example.com newer_than:14d"`) and return normalized
        summaries of the matching messages.
        """
        message_ids = self._client.list_message_ids(query=query, max_results=max_results)
        summaries = [self._to_summary(self._client.get_message(mid)) for mid in message_ids]
        self._log(
            process_id,
            "read",
            f"Searched Gmail for '{query}', found {len(summaries)} message(s)",
            {"query": query, "count": len(summaries)},
        )
        return summaries

    def read_message(self, process_id: str, message_id: str) -> EmailSummary:
        summary = self._to_summary(self._client.get_message(message_id))
        self._log(
            process_id,
            "read",
            f"Read Gmail message '{summary.subject}' from {summary.sender}",
            {"message_id": message_id},
        )
        return summary

    @staticmethod
    def _to_summary(raw: dict[str, Any]) -> EmailSummary:
        headers = {
            h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])
        }
        return EmailSummary(
            message_id=raw["id"],
            thread_id=raw.get("threadId", raw["id"]),
            sender=headers.get("from", "unknown"),
            subject=headers.get("subject", "(no subject)"),
            snippet=raw.get("snippet", ""),
            received_at=headers.get("date"),
        )


class GoogleApiGmailClient:
    """Real Gmail API client, built from OAuth credentials obtained via
    `apm.tools.google_auth.load_credentials`. Imports googleapiclient
    lazily so this module — and GmailTool's unit tests, which use a fake
    client — don't require that dependency at import time.
    """

    def __init__(self, credentials: Any) -> None:
        from googleapiclient.discovery import build

        self._service = build("gmail", "v1", credentials=credentials)

    def list_message_ids(self, query: str, max_results: int) -> list[str]:
        response = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return [m["id"] for m in response.get("messages", [])]

    def get_message(self, message_id: str) -> dict[str, Any]:
        return (
            self._service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )


def build_gmail_tool(state: StateStore, settings: Settings) -> GmailTool:
    """Convenience factory: runs the OAuth flow (if needed) and returns a
    GmailTool backed by the real Gmail API. Used by scripts/gmail_demo.py
    and, later, by the agent — not by unit tests, which construct
    GmailTool directly with a fake client instead.
    """
    from apm.tools.google_auth import load_credentials

    credentials = load_credentials(settings, scopes=[GMAIL_READONLY_SCOPE])
    return GmailTool(state, GoogleApiGmailClient(credentials))
