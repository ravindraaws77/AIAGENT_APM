# Running locally

One repo, one checkout — what you install and what you run is a choice
you make each time, not a different branch or a different project. See
`docs/roadmap.md`'s "Core dependencies split from the NiceGUI
dashboard's" entry for why: `pyproject.toml` declares the integration
layer (`src/apm/tools`/`agent`/`state`) plus its API (`src/apm/api`) as
the core install, and the NiceGUI dashboard (`src/apm/ui`) as an
optional `ui` extra on top of it — `apm.ui` only ever talks to
`apm.api` over HTTP, it never imports `apm.agent`/`apm.tools` directly.

## Prerequisites

- Python 3.10+
- A virtual environment (examples below use `.venv`)
- `.env` filled in from `.env.example` for whichever tools/credentials
  you're actually exercising (not needed to run the test suite — that's
  fully fake-client based)

If you already have a `.venv` from before this split: it was built
against the old flat `requirements.txt`, which no longer exists —
reinstall with the commands below to pick up the new extras.

## Option 1 — full setup (API + dashboard)

This is the normal day-to-day setup, matching what you had before.

```
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -e ".[ui,dev]"
pytest -q
```

Then run the API and the dashboard as two separate processes:

```
# terminal 1
uvicorn apm.api.app:app --reload --port 8000

# terminal 2
python -m apm.ui.app
```

## Option 2 — core only (integration layer + API, no dashboard)

This is how you'd actually deploy the API for a future non-NiceGUI
consumer (e.g. a voice/LiveKit layer) — proves the dashboard's
dependencies (`nicegui`) are never required to run the API.

```
python -m venv .venv-core
.venv-core\Scripts\activate          # Windows
# source .venv-core/bin/activate     # macOS/Linux

pip install -e ".[dev]"
pytest -q
```

`nicegui` won't be installed at all. `pytest` still passes —
`tests/test_ui_pages.py` (the only test file that imports `nicegui`
directly) is automatically skipped, via `conftest.py`.

Run just the API:

```
uvicorn apm.api.app:app --reload --port 8000
```

Confirm the dashboard truly isn't there:

```
python -c "import nicegui"    # should raise ModuleNotFoundError
```

## What `[dev]` and `[ui]` each add

| Extra | Adds | Needed for |
|---|---|---|
| *(none)* | `fastapi`, `uvicorn`, `langgraph`, `anthropic`, `openpyxl`, Google/MS Graph client libs | Running the API/agent/tools layer |
| `dev` | `pytest`, `pytest-asyncio`, `httpx` | Running the test suite (`httpx` is required by FastAPI's `TestClient`, regardless of the dashboard) |
| `ui` | `nicegui`, `httpx` | Running the NiceGUI dashboard (`python -m apm.ui.app`) |

`pip install -e ".[ui,dev]"` installs all three at once.

## Quick sanity check after any dependency change

```
python -c "from apm.api.app import app; print([r.path for r in app.routes])"
```

If that prints the route list with no import errors, the API layer is
intact regardless of what else is or isn't installed.
