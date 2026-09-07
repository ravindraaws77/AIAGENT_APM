from pathlib import Path

import pytest

from apm.config import Settings
from apm.tools.salesforce_auth import acquire_access_token


def _settings(
    *,
    salesforce_client_id: str | None = None,
    salesforce_client_secret: str | None = None,
    salesforce_domain: str | None = None,
) -> Settings:
    return Settings(
        anthropic_api_key=None,
        anthropic_model=None,
        google_client_id=None,
        google_client_secret=None,
        ms_graph_client_id=None,
        ms_graph_client_secret=None,
        ms_graph_tenant_id=None,
        excel_workbook_path=None,
        excel_drive_file_id=None,
        salesforce_client_id=salesforce_client_id,
        salesforce_client_secret=salesforce_client_secret,
        salesforce_domain=salesforce_domain,
        salesforce_api_version=None,
        state_dir=Path("state"),
        tools_api_key=None,
    )


def test_raises_when_unconfigured() -> None:
    with pytest.raises(RuntimeError, match="SALESFORCE_CLIENT_ID"):
        acquire_access_token(_settings())


def test_raises_when_only_client_id_is_set() -> None:
    with pytest.raises(RuntimeError, match="SALESFORCE_CLIENT_ID"):
        acquire_access_token(_settings(salesforce_client_id="id-only"))
