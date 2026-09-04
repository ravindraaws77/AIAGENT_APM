"""Tests for apm.tools.google_auth.build_configured_gmail_and_calendar_tools
-- the "unconfigured -> (None, None)" factory get_tools() uses, same
"the account" spirit as excel_file_tool.build_configured_excel_tool
(tests/test_excel_file_tool.py).
"""

from pathlib import Path

from apm.config import Settings
from apm.state.store import StateStore
from apm.tools.google_auth import build_configured_gmail_and_calendar_tools


def _settings(*, google_client_id: str | None = None, google_client_secret: str | None = None) -> Settings:
    return Settings(
        anthropic_api_key=None,
        anthropic_model=None,
        google_client_id=google_client_id,
        google_client_secret=google_client_secret,
        ms_graph_client_id=None,
        ms_graph_client_secret=None,
        ms_graph_tenant_id=None,
        excel_workbook_path=None,
        excel_drive_file_id=None,
        state_dir=Path("state"),
        tools_api_key=None,
    )


def test_returns_none_none_when_neither_credential_is_set(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    result = build_configured_gmail_and_calendar_tools(store, _settings())

    assert result == (None, None)


def test_returns_none_none_when_only_client_id_is_set(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    result = build_configured_gmail_and_calendar_tools(store, _settings(google_client_id="id-only"))

    assert result == (None, None)


def test_returns_none_none_when_only_client_secret_is_set(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    result = build_configured_gmail_and_calendar_tools(store, _settings(google_client_secret="secret-only"))

    assert result == (None, None)


def test_delegates_to_build_gmail_and_calendar_tools_when_configured(
    tmp_path: Path, monkeypatch
) -> None:
    """Doesn't exercise the real OAuth flow -- just confirms the
    configured path calls through to build_gmail_and_calendar_tools
    (unlike the unconfigured path, which must never reach it, since
    that function raises without credentials).
    """
    import apm.tools.google_auth as google_auth_module

    store = StateStore(tmp_path / "state.json")
    settings = _settings(google_client_id="id", google_client_secret="secret")
    sentinel_gmail = object()
    sentinel_calendar = object()
    calls = []

    def fake_build(state, passed_settings, token_path=google_auth_module.DEFAULT_TOKEN_PATH):
        calls.append((state, passed_settings, token_path))
        return sentinel_gmail, sentinel_calendar

    monkeypatch.setattr(google_auth_module, "build_gmail_and_calendar_tools", fake_build)

    result = build_configured_gmail_and_calendar_tools(store, settings)

    assert result == (sentinel_gmail, sentinel_calendar)
    assert calls == [(store, settings, google_auth_module.DEFAULT_TOKEN_PATH)]
