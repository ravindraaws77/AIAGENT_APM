"""Wipe local app state (processes, history, pending approvals) so a
demo run starts from a clean slate.

Scope, deliberately narrow: this script ONLY deletes the local state/
directory. It never calls the Gmail or Calendar API, never touches
OAuth tokens, and never sends/creates anything -- it has no import of
apm.tools.gmail_tool, apm.tools.calendar_tool, or apm.tools.google_auth
at all. The real Gmail/Calendar seed data scripts/seed_demo_data.py
created lives in your actual sandbox account and is entirely out of
scope here; this script only prints the search query / event titles so
you can review and delete them yourself, manually, via the Gmail/
Calendar web UI -- see .claude/skills/reset-demo-data/SKILL.md for the
full step-by-step, including the separate, optional, manual commands
for clearing cached OAuth tokens or re-seeding.

IMPORTANT: stop the running API (uvicorn) and UI (python -m apm.ui.app)
processes FIRST. The running backend holds process state in memory (the
LangGraph checkpointer); deleting the state file alone won't clear that
for already-running processes -- restarting after this script runs is
what actually gives you a clean slate.

Usage:
  python scripts/reset_demo_data.py          # wipe local state/, with a confirmation prompt
  python scripts/reset_demo_data.py --yes    # skip the confirmation prompt
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = REPO_ROOT / "state"

# Mirrors the order numbers scripts/seed_demo_data.py seeds -- kept here
# too (rather than importing) so this script has no dependency on the
# apm package and can run even if the venv/install is in a broken state
# you're trying to recover from.
SEED_ORDER_NUMBERS = ["401", "402", "403", "404", "405", "406"]

SEED_CALENDAR_EVENT_TITLES = ["Renewal call - Acme Corp", "Contract review - Globex"]


def build_gmail_cleanup_query(order_numbers: list[str]) -> str:
    """The Gmail search query that finds every seeded demo email, for you
    to review and delete yourself. Split out from main() so it's
    unit-testable without touching the filesystem. This value is only
    ever printed -- it is never sent to Gmail by this script.
    """
    subjects = " OR ".join(f'"Order #{n}"' for n in order_numbers)
    return f"subject:({subjects})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (use in scripts/CI; make sure the servers are actually stopped).",
    )
    args = parser.parse_args()

    if not args.yes:
        print("Have you stopped the running API (uvicorn) and UI (python -m apm.ui.app) processes?")
        if input("Type 'yes' to continue: ").strip().lower() != "yes":
            print("Stop them first, then re-run this script.")
            sys.exit(1)

    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)
        print(f"Deleted {STATE_DIR} (processes, history, pending approvals).")
    else:
        print(f"{STATE_DIR} did not exist -- nothing to delete.")

    print(
        "\nLocal state cleared. This script did not touch Gmail, Calendar, or your "
        "cached OAuth tokens -- see .claude/skills/reset-demo-data/SKILL.md for those "
        "optional, separate, manual steps. For reference, the seed data to review there:\n"
    )
    print(f"  Gmail search -> {build_gmail_cleanup_query(SEED_ORDER_NUMBERS)}")
    print(f"  Calendar events -> {' and '.join(repr(t) for t in SEED_CALENDAR_EVENT_TITLES)}\n")
    print("Restart the API and UI processes to pick up the clean state.")


if __name__ == "__main__":
    main()
