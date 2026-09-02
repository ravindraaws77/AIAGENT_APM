"""MS Excel connector (via Microsoft Graph) — read-only for this phase.

Same read-first pattern as gmail_tool.py / calendar_tool.py: writing or
appending rows is documented as a future capability in
docs/capability-map.md, deferred to phase 5 where the LangGraph
human-approval interrupt exists to gate it.

Unlike Gmail/Calendar (which operate on "the" mailbox/calendar), an Excel
connector is bound to one specific workbook — a OneDrive/SharePoint drive
item — chosen when the tool is built. Microsoft Graph's Excel API has no
concept of a local .xlsx file; the workbook must already be on
OneDrive/SharePoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from apm.config import Settings
from apm.state.store import StateStore
from apm.tools.base import BaseTool, Capability

EXCEL_READONLY_SCOPE = "Files.Read"


class ExcelClient(Protocol):
    """The minimal surface ExcelTool needs from a workbook. Both the real
    client (`GraphApiExcelClient`, below) and test fakes implement just
    this.
    """

    def list_worksheets(self) -> list[str]: ...

    def get_range(self, sheet_name: str, address: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RangeData:
    sheet_name: str
    address: str
    values: list[list[Any]] = field(default_factory=list)


class ExcelTool(BaseTool):
    """Read-only Excel connector, bound to one workbook at construction
    time (see build_excel_tool).
    """

    name = "ms_excel"
    capabilities = frozenset({Capability.READ})

    def __init__(self, state: StateStore, client: ExcelClient) -> None:
        super().__init__(state)
        self._client = client

    def health_check(self) -> bool:
        try:
            self._client.list_worksheets()
            return True
        except Exception:
            return False

    def list_worksheets(self, process_id: str) -> list[str]:
        names = self._client.list_worksheets()
        self._log(process_id, "read", f"Listed {len(names)} worksheet(s)", {"worksheets": names})
        return names

    def read_range(self, process_id: str, sheet_name: str, address: str) -> RangeData:
        """Read a cell range (e.g. sheet_name="Renewals", address="A1:D20")
        and return its values as a list of rows.
        """
        raw = self._client.get_range(sheet_name, address)
        data = RangeData(
            sheet_name=sheet_name,
            address=raw.get("address", address),
            values=raw.get("values", []),
        )
        self._log(
            process_id,
            "read",
            f"Read range {sheet_name}!{address} ({len(data.values)} row(s))",
            {"sheet_name": sheet_name, "address": address, "row_count": len(data.values)},
        )
        return data


class GraphApiExcelClient:
    """Real Microsoft Graph client for one workbook (a OneDrive/SharePoint
    drive item). Imports `requests` lazily so this module — and
    ExcelTool's unit tests, which use a fake client — don't require that
    dependency at import time.
    """

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, access_token: str, item_id: str, drive_id: str | None = None) -> None:
        self._access_token = access_token
        # /me/drive/items/{id} for the signed-in user's own OneDrive, or
        # /drives/{drive_id}/items/{id} for a specific SharePoint drive.
        if drive_id:
            self._workbook_base = f"{self.GRAPH_BASE}/drives/{drive_id}/items/{item_id}/workbook"
        else:
            self._workbook_base = f"{self.GRAPH_BASE}/me/drive/items/{item_id}/workbook"

    def _get(self, path: str) -> dict[str, Any]:
        import requests

        response = requests.get(
            f"{self._workbook_base}{path}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def list_worksheets(self) -> list[str]:
        data = self._get("/worksheets")
        return [w["name"] for w in data.get("value", [])]

    def get_range(self, sheet_name: str, address: str) -> dict[str, Any]:
        return self._get(f"/worksheets('{sheet_name}')/range(address='{address}')")


def build_excel_tool(
    state: StateStore, settings: Settings, item_id: str, drive_id: str | None = None
) -> ExcelTool:
    """Convenience factory: runs the device-code auth flow (if needed) and
    returns an ExcelTool bound to the given workbook (drive item id).
    """
    from apm.tools.ms_graph_auth import acquire_access_token

    access_token = acquire_access_token(settings, scopes=[EXCEL_READONLY_SCOPE])
    return ExcelTool(state, GraphApiExcelClient(access_token, item_id, drive_id))
