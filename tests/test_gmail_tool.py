from pathlib import Path
from typing import Any

from apm.state.store import StateStore
from apm.tools.base import Capability
from apm.tools.gmail_tool import GmailTool


class FakeGmailClient:
    """Implements the GmailClient protocol in-memory — no network, no
    credentials — so GmailTool's logic can be unit tested directly.
    """

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = {m["id"]: m for m in messages}
        self.sent: list[dict[str, Any]] = []

    def list_message_ids(self, query: str, max_results: int) -> list[str]:
        return list(self._messages.keys())[:max_results]

    def get_message(self, message_id: str) -> dict[str, Any]:
        return self._messages[message_id]

    def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return {"id": f"sent-{len(self.sent)}"}


class BrokenGmailClient:
    def list_message_ids(self, query: str, max_results: int) -> list[str]:
        raise RuntimeError("simulated API failure")

    def get_message(self, message_id: str) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")

    def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")


def _raw_message(msg_id: str, sender: str, subject: str, snippet: str, date: str) -> dict[str, Any]:
    return {
        "id": msg_id,
        "threadId": f"thread-{msg_id}",
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date},
            ]
        },
    }


def test_gmail_tool_capabilities() -> None:
    assert GmailTool.capabilities == frozenset({Capability.READ, Capability.ACTION})


def test_search_emails_returns_summaries_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient(
        [_raw_message("m1", "customer@example.com", "Order #123 delayed",
                       "Sorry for the delay on your order...", "Mon, 1 Sep 2026 10:00:00 +0000")]
    )
    tool = GmailTool(store, client)

    results = tool.search_emails("order-123", query="order 123", max_results=5)

    assert len(results) == 1
    assert results[0].message_id == "m1"
    assert results[0].sender == "customer@example.com"
    assert results[0].subject == "Order #123 delayed"

    events = store.list_events("order-123")
    assert any(e["event_type"] == "read" and "order 123" in e["details"]["query"] for e in events)


def test_read_message(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([_raw_message("m1", "a@b.com", "Hi there", "snippet text", "date")])
    tool = GmailTool(store, client)

    summary = tool.read_message("order-1", "m1")

    assert summary.message_id == "m1"
    assert summary.subject == "Hi there"


def test_missing_headers_fall_back_to_defaults(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([{"id": "m2", "snippet": "no headers here"}])
    tool = GmailTool(store, client)

    summary = tool.read_message("order-1", "m2")

    assert summary.sender == "unknown"
    assert summary.subject == "(no subject)"
    assert summary.thread_id == "m2"


def test_health_check_true(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = GmailTool(store, FakeGmailClient([]))
    assert tool.health_check() is True


def test_health_check_false_on_client_error(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = GmailTool(store, BrokenGmailClient())
    assert tool.health_check() is False


def test_send_email_dry_run_does_not_call_client(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([])
    tool = GmailTool(store, client)

    result = tool.send_email("order-1", to="c@example.com", subject="Hi", body="body text")

    assert result.executed is False
    assert client.sent == []
    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_proposed" and e["details"]["dry_run"] is True for e in events)


def test_send_email_real_call_invokes_client_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([])
    tool = GmailTool(store, client)

    result = tool.send_email(
        "order-1", to="c@example.com", subject="Delay update", body="Sorry for the delay", dry_run=False
    )

    assert result.executed is True
    assert result.details["message_id"] == "sent-1"
    assert client.sent == [{"to": "c@example.com", "subject": "Delay update", "body": "Sorry for the delay"}]

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_executed" and e["details"]["dry_run"] is False for e in events)
