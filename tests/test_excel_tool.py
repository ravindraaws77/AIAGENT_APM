from pathlib import Path
from typing import Any

from apm.state.store import StateStore
from apm.tools.base import Capability
from apm.tools.excel_tool import ExcelTool


class FakeExcelClient:
    """Implements the ExcelClient protocol in-memory — no network, no
    credentials — so ExcelTool's logic can be unit tested directly.
    """

    def __init__(self, worksheets: list[str], ranges: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._worksheets = worksheets
        self._ranges = ranges

    def list_worksheets(self) -> list[str]:
        return self._worksheets

    def get_range(self, sheet_name: str, address: str) -> dict[str, Any]:
        return self._ranges[(sheet_name, address)]


class BrokenExcelClient:
    def list_worksheets(self) -> list[str]:
        raise RuntimeError("simulated API failure")

    def get_range(self, sheet_name: str, address: str) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")


def test_excel_tool_is_read_only() -> None:
    assert ExcelTool.capabilities == frozenset({Capability.READ})


def test_list_worksheets_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeExcelClient(["Renewals", "Orders"], {})
    tool = ExcelTool(store, client)

    names = tool.list_worksheets("order-123")

    assert names == ["Renewals", "Orders"]
    events = store.list_events("order-123")
    assert any(e["event_type"] == "read" and e["details"]["worksheets"] == names for e in events)


def test_read_range_returns_values_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeExcelClient(
        ["Renewals"],
        {
            ("Renewals", "A1:B2"): {
                "address": "Renewals!A1:B2",
                "values": [["Customer", "RenewalDate"], ["Acme Corp", "2026-10-01"]],
            }
        },
    )
    tool = ExcelTool(store, client)

    data = tool.read_range("order-123", sheet_name="Renewals", address="A1:B2")

    assert data.sheet_name == "Renewals"
    assert data.address == "Renewals!A1:B2"
    assert data.values == [["Customer", "RenewalDate"], ["Acme Corp", "2026-10-01"]]

    events = store.list_events("order-123")
    read_events = [e for e in events if e["event_type"] == "read"]
    assert any(e["details"].get("row_count") == 2 for e in read_events)


def test_read_range_missing_values_defaults_to_empty(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeExcelClient(["Sheet1"], {("Sheet1", "A1:A1"): {}})
    tool = ExcelTool(store, client)

    data = tool.read_range("order-1", sheet_name="Sheet1", address="A1:A1")

    assert data.values == []
    assert data.address == "A1:A1"  # falls back to the requested address


def test_health_check_true(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = ExcelTool(store, FakeExcelClient([], {}))
    assert tool.health_check() is True


def test_health_check_false_on_client_error(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = ExcelTool(store, BrokenExcelClient())
    assert tool.health_check() is False
