"""Gmail connector.

Read (search/read messages) has been available since phase 2. This phase
(5) adds send_email — the write/action capability deferred until now per
the tool-integration skill's "read first" rule, because it needs the
LangGraph human-approval interrupt (apm.agent.graph) to sit in front of
it. send_email still defends in depth on its own: it defaults to
dry_run=True and logs every call via require_dry_run_guard, but the real
gate is the agent never calling it with dry_run=False except after an
approved interrupt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from apm.config import Settings
from apm.state.store import StateStore
from apm.tools.base import ActionResult, BaseTool, Capability

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


class GmailClient(Protocol):
    """The minimal surface GmailTool needs from a Gmail API client. Both
    the real client (`GoogleApiGmailClient`, below) and test fakes
    implement just this, so the connector's logic can be tested without
    live credentials.
    """

    def list_message_ids(self, query: str, max_results: int) -> list[str]: ...

    def get_message(self, message_id: str) -> dict[str, Any]: ...

    def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class EmailSummary:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    received_at: str | None


class GmailTool(BaseTool):
    """Gmail connector: search/read messages, and send an email — the
    latter only ever reachable through the agent's approval interrupt
    (see apm.agent.graph).
    """

    name = "gmail"
    capabilities = frozenset({Capability.READ, Capability.ACTION})

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

    def send_email(
        self, process_id: str, to: str, subject: str, body: str, dry_run: bool = True
    ) -> ActionResult:
        """Send an email. Only ever call this with dry_run=False from
        inside the agent graph, after the human-approval interrupt has
        returned an approval — see apm.agent.graph's execute_node.
        """
        summary = f"Send email to {to}: {subject!r}"
        self.require_dry_run_guard(dry_run, process_id, summary)

        if dry_run:
            return ActionResult(
                executed=False, description=summary, details={"to": to, "subject": subject, "body": body}
            )

        sent = self._client.send_message(to=to, subject=subject, body=body)
        return ActionResult(
            executed=True,
            description=summary,
            details={"to": to, "subject": subject, "message_id": sent.get("id")},
        )

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

    def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]:
        import base64
        from email.mime.text import MIMEText

        mime_message = MIMEText(body)
        mime_message["to"] = to
        mime_message["subject"] = subject
        raw = base64.urlsafe_b64encode(mime_message.as_bytes()).decode("ascii")
        return self._service.users().messages().send(userId="me", body={"raw": raw}).execute()


def build_gmail_tool(state: StateStore, settings: Settings) -> GmailTool:
    """Convenience factory: runs the OAuth flow (if needed) and returns a
    GmailTool backed by the real Gmail API. Used by scripts/gmail_demo.py
    and by the agent (apm.agent.graph) — not by unit tests, which
    construct GmailTool directly with a fake client instead.
    """
    from apm.tools.google_auth import load_credentials

    credentials = load_credentials(settings, scopes=[GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE])
    return GmailTool(state, GoogleApiGmailClient(credentials))
