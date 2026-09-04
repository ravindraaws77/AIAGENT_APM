"""End-to-end smoke-test for the API layer's single free-text entry
point: POST /query -> read the summary + proposed action -> approve/
reject at this terminal -> POST /processes/{id}/decision -> read the
result. Same flow scripts/agent_demo.py runs against the graph directly
(in-process); this one goes over real HTTP instead, the same way a
future non-UI consumer (a voice layer, a curl script, anything) would
-- proof the integration layer's API works standalone, with nothing
NiceGUI-specific involved.

Nothing is sent/created until you type "y" at the approval prompt --
the server-side approval-interrupt gate applies exactly as it does
through the dashboard.

Setup (one-time):
  1. pip install -e ".[integration-layer]"   (no [ui] needed for this)
  2. Configure real credentials per .env.example (ANTHROPIC_API_KEY at
     minimum for the intent parser + reasoner; Google OAuth too if your
     request should actually fetch Gmail/Calendar data).
  3. In one terminal: uvicorn apm.api.app:app --reload --port 8000

Usage:
  python scripts/api_query_demo.py "chase up order 4521"
  python scripts/api_query_demo.py "check the Acme renewal" --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", help="Free-text request, e.g. 'chase up order 4521'")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    args = parser.parse_args()

    try:
        response = requests.post(f"{args.base_url}/query", json={"text": args.text}, timeout=60)
    except requests.exceptions.ConnectionError:
        raise SystemExit(f"Could not connect to {args.base_url} -- is `uvicorn apm.api.app:app --port 8000` running?")

    if response.status_code >= 400:
        raise SystemExit(f"POST /query failed: HTTP {response.status_code} -- {response.text}")

    outcome = response.json()
    process_id = outcome["process_id"]
    print(f"\nProcess: {process_id}")
    print(f"Summary: {outcome['summary']}\n")

    pending = outcome.get("pending_action")
    if not pending:
        print(f"No action proposed. Result: {outcome.get('final_result')}")
        return

    print(f"Proposed action ({pending['tool']}.{pending['method']}): {pending['description']}")
    print(f"Details: {json.dumps(pending['payload'], indent=2)}\n")
    answer = input("Approve this action? [y/N] ").strip().lower()

    decision = requests.post(
        f"{args.base_url}/processes/{process_id}/decision",
        json={"approved": answer == "y"},
        timeout=60,
    )
    if decision.status_code >= 400:
        raise SystemExit(f"POST /decision failed: HTTP {decision.status_code} -- {decision.text}")

    print(f"\nResult: {decision.json().get('final_result')}")


if __name__ == "__main__":
    main()
