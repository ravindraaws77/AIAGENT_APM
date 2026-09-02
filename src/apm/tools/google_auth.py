"""Shared Google OAuth helper for the Gmail and Calendar connectors — they
use the same installed-app consent flow and can share a token cache.

This module only produces authorized credentials; it never touches
Gmail/Calendar data itself. Google's auth libraries are imported lazily
inside the function so the rest of the codebase (and any test that only
exercises a connector's logic with a fake client) doesn't need those
dependencies installed.
"""

from __future__ import annotations

from pathlib import Path

from apm.config import Settings

DEFAULT_TOKEN_PATH = Path(".google_token.json")


def load_credentials(
    settings: Settings,
    scopes: list[str],
    token_path: Path = DEFAULT_TOKEN_PATH,
):
    """Return authorized Google credentials for the given scopes, running
    the one-time browser consent flow if there's no cached token yet, or
    refreshing a cached token if it's expired.

    `token_path` is a local, gitignored file (see .gitignore's
    `*token*.json` pattern) — never commit it, it grants account access.

    Note on combining Gmail + Calendar: a cached token is only valid for
    the scopes it was originally consented to. If you call this with the
    Gmail scope alone and later with the Calendar scope alone, you'll get
    two separate consent prompts writing to the same token_path, and the
    second overwrites the first — the earlier tool then fails at request
    time with an insufficient-scope error, not at token-load time. When
    phase 5 wires up both tools together, request both scopes in one
    call (e.g. `load_credentials(settings, [GMAIL_READONLY_SCOPE, CALENDAR_READONLY_SCOPE])`)
    so one consent covers both, or use separate token_path values per tool.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not settings.google_client_id or not settings.google_client_secret:
                raise RuntimeError(
                    "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set. "
                    "See .env.example for how to obtain them from Google "
                    "Cloud Console, then set them in your local .env."
                )
            client_config = {
                "installed": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, scopes)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return creds
