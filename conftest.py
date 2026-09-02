"""Registers NiceGUI's `user` test fixture (tests/test_ui_pages.py).

Must live at the repository root, not under tests/: pytest disallows
`pytest_plugins` declarations in a non-root conftest.py. See
docs/roadmap.md and pyproject.toml's `main_file` setting for how the
fixture finds the dashboard app under test.
"""

pytest_plugins = ["nicegui.testing.user_plugin"]
