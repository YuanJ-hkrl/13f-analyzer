"""Extract unique security records from holdings into the securities table."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from db import get_connection

logger = logging.getLogger(__name__)


def _build_security_rows() -> list[dict[str, Any]]:
    """Collect the unique security identifiers used in holdings."""
    print("Connecting to Azure SQL and collecting unique tickers from holdings...")
    with get_connection() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    h.ticker,
                    MAX(h.cusip) AS cusip,
                    MAX(h.issuer_name) AS issuer_name,
                    MIN(f.report_period) AS first_appearance_date
                FROM (
                    SELECT DISTINCT
                        TRIM(ticker) AS ticker,
                        filing_id,
                        cusip,
                        issuer_name
                    FROM holdings
                    WHERE ticker IS NOT NULL
                      AND TRIM(ticker) <> ''
                ) h
                INNER JOIN filings f ON f.id = h.filing_id
                GROUP BY h.ticker
                ORDER BY h.ticker
                """
            )
        ).mappings().all()

    records: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row["ticker"]).strip()
        if not ticker:
            continue
        records.append(
            {
                "ticker": ticker,
                "cusip": row["cusip"],
                "issuer_name": row["issuer_name"],
                "first_appearance_date": row["first_appearance_date"],
            }
        )

    print(f"Found {len(records)} unique tickers in holdings.")
    return records


def sync_securities() -> dict[str, int]:
    """Upsert unique securities derived from holdings into the securities table."""
    rows = _build_security_rows()
    stats = {"distinct_tickers": len(rows), "rows_upserted": 0}

    if not rows:
        print("No securities to write.")
        return stats

    print("Upserting unique securities into the securities table...")
    with get_connection() as conn:
        conn.execute(
            text(
                """
                MERGE securities AS target
                USING (
                    VALUES (:ticker, :cusip, :issuer_name, :first_appearance_date)
                ) AS source (ticker, cusip, issuer_name, first_appearance_date)
                ON target.ticker = source.ticker
                WHEN MATCHED THEN
                    UPDATE SET
                        cusip = COALESCE(source.cusip, target.cusip),
                        issuer_name = COALESCE(source.issuer_name, target.issuer_name),
                        first_appearance_date = source.first_appearance_date,
                        updated_at = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN
                    INSERT (ticker, cusip, issuer_name, first_appearance_date, created_at, updated_at)
                    VALUES (source.ticker, source.cusip, source.issuer_name, source.first_appearance_date,
                            SYSUTCDATETIME(), SYSUTCDATETIME());
                """
            ),
            rows,
        )
        conn.commit()

    stats["rows_upserted"] = len(rows)
    print(f"Completed securities sync: {stats}")
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Starting securities extraction...")
    result = sync_securities()
    print("Final result:")
    print(result)
