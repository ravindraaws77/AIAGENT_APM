from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from apm.state.store import StateStore
from apm.tools.base import Capability
from apm.tools.excel_file_tool import ExcelFileTool, LocalWorkbookSource


class FakeWorkbookSource:
    """Implements the WorkbookSource protocol in-memory — no disk, no
    network, no credentials — so ExcelFileTool's logic can be unit
    tested directly, for both the local-file and Google-Drive cases
    (they only differ in where the bytes ultimately live).
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.write_count = 0

    def describe(self) -> str:
        return "fake:workbook"

    def read_bytes(self) -> bytes:
        return self._data

    def write_bytes(self, data: bytes) -> None:
        self._data = data
        self.write_count += 1


class BrokenWorkbookSource:
    def describe(self) -> str:
        return "fake:broken"

    def read_bytes(self) -> bytes:
        raise RuntimeError("simulated read failure")

    def write_bytes(self, data: bytes) -> None:
        raise RuntimeError("simulated write failure")


def _sample_workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Renewals"
    sheet.append(["Customer", "RenewalDate"])
    sheet.append(["Acme Corp", "2026-10-01"])
    workbook.create_sheet("Orders")
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_excel_file_tool_capabilities() -> None:
    assert ExcelFileTool.capabilities == frozenset({Capability.READ, Capability.WRITE})


def test_list_worksheets_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    names = tool.list_worksheets("order-123")

    assert names == ["Renewals", "Orders"]
    events = store.list_events("order-123")
    assert any(e["event_type"] == "read" and e["details"]["worksheets"] == names for e in events)


def test_read_range_returns_values_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    data = tool.read_range("order-123", sheet_name="Renewals", address="A1:B2")

    assert data.sheet_name == "Renewals"
    assert data.address == "A1:B2"
    assert data.values == [["Customer", "RenewalDate"], ["Acme Corp", "2026-10-01"]]

    events = store.list_events("order-123")
    read_events = [e for e in events if e["event_type"] == "read"]
    assert any(e["details"].get("row_count") == 2 for e in read_events)


def test_read_range_single_cell_address(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    data = tool.read_range("order-1", sheet_name="Renewals", address="A2")

    assert data.values == [["Acme Corp"]]


def test_health_check_true(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = ExcelFileTool(store, FakeWorkbookSource(_sample_workbook_bytes()))
    assert tool.health_check() is True


def test_health_check_false_on_source_error(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = ExcelFileTool(store, BrokenWorkbookSource())
    assert tool.health_check() is False


def test_write_range_dry_run_does_not_touch_source(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    result = tool.write_range("order-1", sheet_name="Renewals", address="A2:B2", values=[["Acme", "2026-11-01"]])

    assert result.executed is False
    assert source.write_count == 0
    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_proposed" and e["details"]["dry_run"] is True for e in events)


def test_write_range_real_call_updates_source_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    result = tool.write_range(
        "order-1", sheet_name="Renewals", address="A2:B2", values=[["Acme", "2026-11-01"]], dry_run=False
    )

    assert result.executed is True
    assert result.details["row_count"] == 1
    assert source.write_count == 1

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_executed" and e["details"]["dry_run"] is False for e in events)

    # The write actually landed, and other data (Orders sheet) survived.
    reread = tool.read_range("order-1", sheet_name="Renewals", address="A2:B2")
    assert reread.values == [["Acme", "2026-11-01"]]
    assert tool.list_worksheets("order-1") == ["Renewals", "Orders"]


def test_local_workbook_source_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "workbook.xlsx"
    path.write_bytes(_sample_workbook_bytes())
    source = LocalWorkbookSource(path)

    assert source.describe() == f"local:{path}"
    assert source.read_bytes() == path.read_bytes()

    source.write_bytes(b"new-bytes")
    assert path.read_bytes() == b"new-bytes"
