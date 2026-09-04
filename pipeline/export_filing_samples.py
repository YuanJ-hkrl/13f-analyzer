#!/usr/bin/env python3
"""Download representative SEC 13F filings for parser diagnosis."""

from __future__ import annotations

import json
import re
from pathlib import Path

from edgar import Company, set_identity

from config import SEC_IDENTITY
from edgar_13f import _normalize_holdings_df


SAMPLES = [
    ("Coatue Management LLC", "1135730", "0000919574-26-001239", "broken-2025-q4"),
    ("OLP Capital Management Ltd.", "1738126", "0001738126-26-000004", "broken-2026-q1"),
    ("Coatue Management LLC", "1135730", "0000919574-26-005478", "healthy-2026-q2"),
]
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "filing_samples"


def safe_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def main() -> int:
    set_identity(SEC_IDENTITY)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []

    for fund_name, cik, accession, label in SAMPLES:
        filings = Company(cik).get_filings(form="13F-HR")
        filing = next((item for item in filings if item.accession_no == accession), None)
        if filing is None:
            raise RuntimeError(f"Could not find {accession} for {fund_name}")

        report = filing.obj()
        raw = report.infotable if hasattr(report, "infotable") else report.holdings
        normalized = _normalize_holdings_df(raw.copy())
        prefix = f"{label}-{safe_name(fund_name)}-{accession}"
        raw_path = OUTPUT_DIR / f"{prefix}-raw.csv"
        normalized_path = OUTPUT_DIR / f"{prefix}-normalized.csv"
        raw.to_csv(raw_path, index=False)
        normalized.to_csv(normalized_path, index=False)
        manifest.append({
            "label": label,
            "fund": fund_name,
            "cik": cik,
            "accession": accession,
            "raw_columns": list(raw.columns),
            "raw_rows": len(raw),
            "normalized_positive_share_rows": int((normalized["shares"] > 0).sum()),
            "raw_csv": str(raw_path),
            "normalized_csv": str(normalized_path),
        })
        print(f"Exported {label}: {len(raw)} rows, columns={list(raw.columns)}")

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
