"""Read-only smoke-test for the API layer, run directly against a live
server -- no Anthropic/Google/MS credentials needed, since this only
exercises the read routes (they just query the state store, never a
tool or the reasoner). Good first check that the integration layer's
API is up and reachable at all, independent of the NiceGUI dashboard --
exactly what a future non-UI consumer (a voice layer, say) would do
first too.

Setup (one-time):
  1. pip install -e ".[integration-layer]"   (no [ui] needed for this)
  2. In one terminal: uvicorn apm.api.app:app --reload --port 8000

Usage:
  python scripts/api_smoke_test.py
  python scripts/api_smoke_test.py --base-url http://127.0.0.1:8000
  python scripts/api_smoke_test.py --process-id order-123
"""

from __future__ import annotations

import argparse
import sys

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--process-id", default=None, help="Also print status/history/pending for this process id")
    args = parser.parse_args()

    ok = True
    ok &= _check("GET /health", lambda: requests.get(f"{args.base_url}/health", timeout=5))
    ok &= _check("GET /processes", lambda: requests.get(f"{args.base_url}/processes", timeout=5))

    if args.process_id:
        pid = args.process_id
        ok &= _check(f"GET /processes/{pid}/status", lambda: requests.get(f"{args.base_url}/processes/{pid}/status", timeout=5))
        ok &= _check(f"GET /processes/{pid}/history", lambda: requests.get(f"{args.base_url}/processes/{pid}/history", timeout=5))
        ok &= _check(f"GET /processes/{pid}/pending", lambda: requests.get(f"{args.base_url}/processes/{pid}/pending", timeout=5))

    sys.exit(0 if ok else 1)


def _check(label: str, call) -> bool:
    """A reachable server that responds -- even with a 404 for an
    unknown process id, a legitimate answer, not a smoke-test failure
    -- counts as OK. Only a dropped connection or a 5xx (the server
    itself breaking) counts as FAIL.
    """
    try:
        response = call()
    except requests.exceptions.ConnectionError:
        print(f"[FAIL] {label}: could not connect -- is `uvicorn apm.api.app:app --port 8000` running?")
        return False

    if response.status_code >= 500:
        print(f"[FAIL] {label}: HTTP {response.status_code} -- {response.text}")
        return False

    print(f"[ OK ] {label}: HTTP {response.status_code}")
    print(f"       {response.json()}")
    return True


if __name__ == "__main__":
    main()
