"""Look up SEC CIK numbers for fund names via EDGAR company search."""

from __future__ import annotations

import json
import sys
import time

import requests

from config import FUNDS_JSON, SEC_IDENTITY

SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"


def search_cik(name: str) -> str | None:
    """Search EDGAR for a company CIK by name."""
    headers = {"User-Agent": SEC_IDENTITY}
    params = {
        "q": name,
        "forms": "13F-HR",
    }
    try:
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={"q": f'"{name}"', "dateRange": "custom", "startdt": "2020-01-01", "enddt": "2026-12-31"},
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            # Fallback: SEC submissions API search
            resp = requests.get(
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={name}&type=13F-HR&dateb=&owner=include&count=1&search_text=&action=getcompany&output=atom",
                headers=headers,
                timeout=15,
            )
            return None

        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        if hits:
            cik = hits[0].get("_source", {}).get("ciks", [None])[0]
            return str(cik).lstrip("0") if cik else None
    except Exception as e:
        print(f"  Error searching {name}: {e}", file=sys.stderr)
    return None


def lookup_all_funds() -> list[dict]:
    with open(FUNDS_JSON) as f:
        funds = json.load(f)

    results = []
    for fund in funds:
        name = fund["name"]
        existing_cik = fund.get("cik")
        print(f"Searching: {name}...", file=sys.stderr)
        cik = search_cik(name.replace(" Ltd.", "").replace(" LP", "").replace(" LLC", ""))
        results.append({**fund, "cik": cik or existing_cik})
        time.sleep(0.2)  # SEC rate limit courtesy

    return results


if __name__ == "__main__":
    updated = lookup_all_funds()
    print(json.dumps(updated, indent=2))
