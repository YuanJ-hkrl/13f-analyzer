#!/usr/bin/env python3
"""Apply the persisted-position migration using the configured DATABASE_URL."""

from __future__ import annotations

import re
from pathlib import Path

from db import get_connection


MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "database"
    / "add_performance_summaries.sql"
)


def main() -> int:
    sql = MIGRATION.read_text(encoding="utf-8")
    batches = [
        batch.strip()
        for batch in re.split(r"^\s*GO\s*$", sql, flags=re.IGNORECASE | re.MULTILINE)
        if batch.strip()
    ]

    with get_connection() as conn:
        for number, batch in enumerate(batches, start=1):
            print(f"Applying migration batch {number}/{len(batches)}...")
            conn.exec_driver_sql(batch)
            conn.commit()

    print("Performance summary migration applied successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
