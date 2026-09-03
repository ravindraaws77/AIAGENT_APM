"""Registers NiceGUI's `user` test fixture (tests/test_ui_pages.py), when
the optional `ui` extra (nicegui) is installed.

Must live at the repository root, not under tests/: pytest disallows
`pytest_plugins` declarations in a non-root conftest.py. See
docs/roadmap.md and pyproject.toml's `main_file` setting for how the
fixture finds the dashboard app under test.

A core-only install (`pip install .` / `.[dev]`, no `[ui]`) has no
nicegui -- skip the plugin and the dashboard-only test file instead of
failing collection, so the API/tools/agent layer's own test suite still
runs standalone.
"""

import importlib.util

if importlib.util.find_spec("nicegui") is not None:
    pytest_plugins = ["nicegui.testing.user_plugin"]
else:
    collect_ignore = ["tests/test_ui_pages.py"]
