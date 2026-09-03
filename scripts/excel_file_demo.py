"""Manual smoke-test for the local/Google Drive Excel connector
(src/apm/tools/excel_file_tool.py) — not part of the automated test
suite (that uses a fake source, see tests/test_excel_file_tool.py).

Local file usage (no credentials needed):
  python scripts/excel_file_demo.py local <path.xlsx> <sheet_name> <range_address>
  python scripts/excel_file_demo.py local ./workbook.xlsx Sheet1 A1:D10

Google Drive usage:
  Setup (one-time): copy .env.example to .env, fill in GOOGLE_CLIENT_ID /
  GOOGLE_CLIENT_SECRET (Google Cloud Console -> enable the Drive API on
  the same OAuth client used for Gmail/Calendar). First run opens a
  browser consent screen and caches a token locally
  (.google_drive_token.json, gitignored).

  # Find the Drive file id of an .xlsx file (from its Drive share URL,
  # or list files with --list):
  python scripts/excel_file_demo.py gdrive --list
  python scripts/excel_file_demo.py gdrive <file_id> <sheet_name> <range_address>

Both modes only call read-only methods here — nothing is written to the
workbook.
"""

from __future__ import annotations

import sys

from apm.config import load_settings
from apm.state.store import StateStore
from apm.tools.excel_file_tool import (
    GOOGLE_DRIVE_READONLY_SCOPE,
    build_gdrive_excel_tool,
    build_local_excel_tool,
)


def list_drive_files() -> None:
    from apm.tools.excel_file_tool import DEFAULT_DRIVE_TOKEN_PATH, EXCEL_MIME_TYPE
    from apm.tools.google_auth import load_credentials

    settings = load_settings()
    credentials = load_credentials(
        settings, scopes=[GOOGLE_DRIVE_READONLY_SCOPE], token_path=DEFAULT_DRIVE_TOKEN_PATH
    )
    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=credentials)
    response = (
        service.files()
        .list(q=f"mimeType='{EXCEL_MIME_TYPE}'", fields="files(id, name)")
        .execute()
    )
    for item in response.get("files", []):
        print(f"{item['id']}  {item['name']}")


def run(tool, sheet_name: str, address: str) -> None:
    if not tool.health_check():
        print("Excel file connector health check failed — check the path/file id and credentials.")
        return

    print(f"Worksheets: {tool.list_worksheets(process_id='demo')}\n")

    data = tool.read_range(process_id="demo", sheet_name=sheet_name, address=address)
    print(f"{data.sheet_name}!{data.address}")
    for row in data.values:
        print(row)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    mode, *rest = args

    if mode == "local":
        if len(rest) != 3:
            print(__doc__)
            return
        path, sheet_name, address = rest
        store = StateStore()
        run(build_local_excel_tool(store, path), sheet_name, address)
        return

    if mode == "gdrive":
        if rest and rest[0] == "--list":
            list_drive_files()
            return
        if len(rest) != 3:
            print(__doc__)
            return
        file_id, sheet_name, address = rest
        settings = load_settings()
        store = StateStore()
        run(build_gdrive_excel_tool(store, settings, file_id=file_id), sheet_name, address)
        return

    print(__doc__)


if __name__ == "__main__":
    main()
