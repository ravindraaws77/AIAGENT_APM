"""Environment/config loading. No secrets ever live in this file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv is a dev convenience; absence just means the caller
    # is expected to export env vars some other way (shell, CI secrets, ...).
    pass

STATE_DIR = Path(os.environ.get("APM_STATE_DIR", "state"))


@dataclass(frozen=True)
class Settings:
    """Snapshot of the environment variables APM cares about.

    Values are read lazily via `load_settings()` rather than at import
    time, so tests can monkeypatch `os.environ` before calling it.
    """

    anthropic_api_key: str | None
    anthropic_model: str | None
    google_client_id: str | None
    google_client_secret: str | None
    ms_graph_client_id: str | None
    ms_graph_client_secret: str | None
    ms_graph_tenant_id: str | None
    excel_workbook_path: str | None
    excel_drive_file_id: str | None
    state_dir: Path


def load_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL"),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        ms_graph_client_id=os.environ.get("MS_GRAPH_CLIENT_ID"),
        ms_graph_client_secret=os.environ.get("MS_GRAPH_CLIENT_SECRET"),
        ms_graph_tenant_id=os.environ.get("MS_GRAPH_TENANT_ID"),
        excel_workbook_path=os.environ.get("APM_EXCEL_WORKBOOK_PATH"),
        excel_drive_file_id=os.environ.get("APM_EXCEL_DRIVE_FILE_ID"),
        state_dir=STATE_DIR,
    )
