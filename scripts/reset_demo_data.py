"""Reset the local demo environment: clears persisted process/history
state (and, optionally, cached OAuth tokens), then prints the manual
steps for cleaning up the real Gmail/Calendar data scripts/seed_demo_data.py
created.

The manual step exists because there's no delete capability built into
the tool connectors (see docs/capability-map.md) -- Gmail/Calendar
cleanup can't be automated the way the rest of this script is.

IMPORTANT: stop the running API (uvicorn) and UI (python -m apm.ui.app)
processes FIRST. The running backend holds process state in memory (the
LangGraph checkpointer); deleting the state file alone won't clear that
for already-running processes -- restarting after this script runs is
what actually gives you a clean slate.

Usage:
  python scripts/reset_demo_data.py                              # clear local state only
  python scripts/reset_demo_data.py --tokens                      # also clear cached OAuth tokens
  python scripts/reset_demo_data.py --reseed you@example.com      # clear, then reseed
  python scripts/reset_demo_data.py --yes                         # skip the "did you stop the servers?" prompt
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = REPO_ROOT / "state"
GOOGLE_TOKEN = REPO_ROOT / ".google_token.json"
MS_GRAPH_TOKEN = REPO_ROOT / ".ms_graph_token_cache.json"

# Mirrors the order numbers scripts/seed_demo_data.py seeds -- kept here
# too (rather than importing) so this script has no dependency on the
# apm package and can run even if the venv/install is in a broken state
# you're trying to recover from.
SEED_ORDER_NUMBERS = ["401", "402", "403", "404", "405", "406"]

SEED_CALENDAR_EVENT_TITLES = ["Renewal call - Acme Corp", "Contract review - Globex"]


def build_gmail_cleanup_query(order_numbers: list[str]) -> str:
    """The Gmail search query that finds every seeded demo email, for
    manual review/deletion. Split out from main() so it's unit-testable
    without touching the filesystem.
    """
    subjects = " OR ".join(f'"Order #{n}"' for n in order_numbers)
    return f"subject:({subjects})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--tokens",
        action="store_true",
        help="Also delete cached Google/Microsoft OAuth tokens, forcing fresh sign-in next run.",
    )
    parser.add_argument(
        "--reseed",
        metavar="CONTACT_EMAIL",
        default=None,
        help="After clearing, immediately re-run scripts/seed_demo_data.py with this contact email.",
    )
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

    if args.tokens:
        for token_path in (GOOGLE_TOKEN, MS_GRAPH_TOKEN):
            if token_path.exists():
                token_path.unlink()
                print(f"Deleted {token_path.name} -- you'll be prompted to sign in again next run.")

    print(
        "\nLocal state cleared. The real Gmail/Calendar seed data still exists in your "
        "sandbox account -- there's no delete capability built into the tools, so clean "
        "that up manually:\n"
    )
    print(f"  Gmail: search and delete -> {build_gmail_cleanup_query(SEED_ORDER_NUMBERS)}")
    print(f"  Calendar: delete {' and '.join(repr(t) for t in SEED_CALENDAR_EVENT_TITLES)}\n")

    if args.reseed:
        print(f"Re-seeding demo data for contact {args.reseed}...\n")
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "seed_demo_data.py"), args.reseed], check=True
        )

    print("\nDone. Restart the API and UI processes to pick up the clean state.")


if __name__ == "__main__":
    main()
