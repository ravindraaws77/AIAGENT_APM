"""Tests for the /tools/* API-key auth gate (apm.api.auth.require_tools_api_key),
applied at the tools_routes router level. Uses the real dependency (not
overridden) with APM_TOOLS_API_KEY monkeypatched, so it exercises the
actual env-var-driven behavior a deployment would see.
"""

from pathlib import Path

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from apm.agent.graph import build_action_graph
from apm.api.app import create_app
from apm.api.dependencies import get_action_graph, get_tools
from apm.state.store import StateStore
from apm.tools.excel_file_tool import ExcelFileTool
from tests.test_excel_file_tool import FakeWorkbookSource, _sample_workbook_bytes


def _client(tmp_path: Path) -> TestClient:
    store = StateStore(tmp_path / "state.json")
    excel_source = FakeWorkbookSource(_sample_workbook_bytes())
    tools = {"excel_file": ExcelFileTool(store, excel_source)}
    action_graph = build_action_graph(tools, store, checkpointer=MemorySaver())

    app = create_app()
    app.dependency_overrides[get_tools] = lambda: tools
    app.dependency_overrides[get_action_graph] = lambda: action_graph
    return TestClient(app)


def test_no_key_configured_allows_unauthenticated_requests(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("APM_TOOLS_API_KEY", raising=False)
    client = _client(tmp_path)

    response = client.post("/tools/excel/worksheets", json={"process_id": "order-1"})

    assert response.status_code == 200


def test_key_configured_rejects_missing_header(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APM_TOOLS_API_KEY", "secret-key")
    client = _client(tmp_path)

    response = client.post("/tools/excel/worksheets", json={"process_id": "order-1"})

    assert response.status_code == 401


def test_key_configured_rejects_wrong_header(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APM_TOOLS_API_KEY", "secret-key")
    client = _client(tmp_path)

    response = client.post(
        "/tools/excel/worksheets", json={"process_id": "order-1"}, headers={"X-API-Key": "wrong"}
    )

    assert response.status_code == 401


def test_key_configured_accepts_correct_header_for_a_read(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APM_TOOLS_API_KEY", "secret-key")
    client = _client(tmp_path)

    response = client.post(
        "/tools/excel/worksheets", json={"process_id": "order-1"}, headers={"X-API-Key": "secret-key"}
    )

    assert response.status_code == 200


def test_key_configured_gates_a_write_route_too(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APM_TOOLS_API_KEY", "secret-key")
    client = _client(tmp_path)
    body = {"process_id": "order-1", "sheet_name": "Sheet1", "address": "A1", "values": [["x"]]}

    unauthenticated = client.post("/tools/excel/write", json=body)
    authenticated = client.post("/tools/excel/write", json=body, headers={"X-API-Key": "secret-key"})

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200


def test_key_configured_does_not_gate_health(tmp_path: Path, monkeypatch) -> None:
    """The auth dependency is scoped to the /tools/* router only -- the
    existing /health and reasoning-flow routes are unaffected.
    """
    monkeypatch.setenv("APM_TOOLS_API_KEY", "secret-key")
    client = _client(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
