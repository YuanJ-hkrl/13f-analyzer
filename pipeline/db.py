"""Database utilities for Azure SQL."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Generator, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import DATABASE_URL, FUNDS_JSON


def get_engine() -> Engine:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure your Azure SQL connection string."
        )
    return create_engine(DATABASE_URL, pool_pre_ping=True)


@contextmanager
def get_connection() -> Generator:
    engine = get_engine()
    with engine.connect() as conn:
        yield conn


def log_sync_start(conn, job_type: str) -> int:
    result = conn.execute(
        text(
            """
            INSERT INTO sync_log (job_type, status, started_at)
            OUTPUT INSERTED.id
            VALUES (:job_type, 'started', SYSUTCDATETIME())
            """
        ),
        {"job_type": job_type},
    )
    log_id = result.scalar_one()
    conn.commit()
    return log_id


def log_sync_finish(
    conn,
    log_id: int,
    status: str,
    message: str = "",
    records_affected: int = 0,
) -> None:
    conn.execute(
        text(
            """
            UPDATE sync_log
            SET status = :status,
                message = :message,
                records_affected = :records_affected,
                finished_at = SYSUTCDATETIME()
            WHERE id = :id
            """
        ),
        {
            "id": log_id,
            "status": status,
            "message": message[:4000] if message else None,
            "records_affected": records_affected,
        },
    )
    conn.commit()


def seed_funds(conn) -> int:
    """Insert fund list from funds.json if not already present."""
    with open(FUNDS_JSON) as f:
        funds = json.load(f)

    inserted = 0
    for fund in funds:
        result = conn.execute(
            text(
                """
                IF NOT EXISTS (SELECT 1 FROM funds WHERE name = :name)
                BEGIN
                    INSERT INTO funds (name, fund_type, cik)
                    VALUES (:name, :fund_type, :cik)
                END
                """
            ),
            {
                "name": fund["name"],
                "fund_type": fund["fund_type"],
                "cik": fund.get("cik"),
            },
        )
        inserted += result.rowcount
    conn.commit()
    return inserted


def get_funds(conn, active_only: bool = True) -> list[dict[str, Any]]:
    query = "SELECT id, name, fund_type, cik FROM funds"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY fund_type, name"
    rows = conn.execute(text(query)).mappings().all()
    return [dict(r) for r in rows]


def get_fund_by_id(conn, fund_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute(
        text("SELECT id, name, fund_type, cik FROM funds WHERE id = :id"),
        {"id": fund_id},
    ).mappings().first()
    return dict(row) if row else None


def filing_exists(conn, accession_no: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM filings WHERE accession_no = :acc"),
        {"acc": accession_no},
    ).first()
    return row is not None


def insert_filing(
    conn,
    fund_id: int,
    accession_no: str,
    report_period: date,
    filing_date: date,
    total_value: Optional[int],
    total_holdings: Optional[int],
    form_type: str = "13F-HR",
) -> int:
    result = conn.execute(
        text(
            """
            INSERT INTO filings (fund_id, accession_no, form_type, report_period, filing_date, total_value, total_holdings)
            OUTPUT INSERTED.id
            VALUES (:fund_id, :accession_no, :form_type, :report_period, :filing_date, :total_value, :total_holdings)
            """
        ),
        {
            "fund_id": fund_id,
            "accession_no": accession_no,
            "form_type": form_type,
            "report_period": report_period,
            "filing_date": filing_date,
            "total_value": total_value,
            "total_holdings": total_holdings,
        },
    )
    filing_id = result.scalar_one()
    conn.commit()
    return filing_id


def insert_holdings(conn, filing_id: int, fund_id: int, holdings_df: pd.DataFrame) -> int:
    if holdings_df.empty:
        return 0

    records = []
    for _, row in holdings_df.iterrows():
        records.append(
            {
                "filing_id": filing_id,
                "fund_id": fund_id,
                "cusip": _safe_str(row.get("cusip")),
                "ticker": _safe_str(row.get("ticker")),
                "issuer_name": _safe_str(row.get("issuer_name")) or "Unknown",
                "security_class": _safe_str(row.get("security_class")),
                "shares": int(row.get("shares") or 0),
                "value_usd": int(row.get("value_usd") or 0),
                "put_call": _safe_str(row.get("put_call")),
                "investment_discretion": _safe_str(row.get("investment_discretion")),
            }
        )

    conn.execute(
        text(
            """
            INSERT INTO holdings
                (filing_id, fund_id, cusip, ticker, issuer_name, security_class,
                 shares, value_usd, put_call, investment_discretion)
            VALUES
                (:filing_id, :fund_id, :cusip, :ticker, :issuer_name, :security_class,
                 :shares, :value_usd, :put_call, :investment_discretion)
            """
        ),
        records,
    )
    conn.commit()
    return len(records)


def upsert_daily_prices(conn, prices_df: pd.DataFrame) -> int:
    if prices_df.empty:
        return 0

    records = []
    for _, row in prices_df.iterrows():
        records.append(
            {
                "ticker": row["ticker"],
                "price_date": row["price_date"],
                "close_price": row.get("close_price"),
                "adj_close": row.get("adj_close"),
            }
        )

    conn.execute(
        text(
            """
            MERGE daily_prices AS target
            USING (SELECT :ticker AS ticker, :price_date AS price_date) AS source
            ON target.ticker = source.ticker AND target.price_date = source.price_date
            WHEN MATCHED THEN
                UPDATE SET
                    close_price = :close_price,
                    adj_close = :adj_close
            WHEN NOT MATCHED THEN
                INSERT (ticker, price_date, close_price, adj_close)
                VALUES (:ticker, :price_date, :close_price, :adj_close);
            """
        ),
        records,
    )
    conn.commit()
    return len(records)


def get_distinct_tickers(conn) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ticker FROM holdings
            WHERE ticker IS NOT NULL AND ticker != ''
            UNION
            SELECT DISTINCT ticker FROM securities
            """
        )
    ).fetchall()
    return sorted({r[0] for r in rows if r[0]})


def get_tickers_with_first_appearance(conn) -> dict[str, date]:
    """Return securities keyed by ticker with their earliest 13F report date."""
    rows = conn.execute(
        text(
            """
            SELECT ticker, first_appearance_date
            FROM securities
            WHERE ticker IS NOT NULL
              AND ticker != ''
              AND first_appearance_date IS NOT NULL
            ORDER BY ticker
            """
        )
    ).fetchall()
    return {str(row[0]).strip().upper(): row[1] for row in rows}


def get_fund_holdings_for_period(conn, fund_id: int, report_period: date) -> pd.DataFrame:
    return pd.read_sql(
        text(
            """
            SELECT h.ticker, h.cusip, h.issuer_name, h.shares, h.value_usd, h.put_call,
                   f.report_period, f.filing_date
            FROM holdings h
            JOIN filings f ON h.filing_id = f.id
            WHERE h.fund_id = :fund_id
              AND f.report_period = :report_period
              AND (h.put_call IS NULL OR h.put_call = '')
            """
        ),
        conn,
        params={"fund_id": fund_id, "report_period": report_period},
    )


def get_fund_filing_periods(conn, fund_id: int) -> list[date]:
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT report_period FROM filings
            WHERE fund_id = :fund_id
            ORDER BY report_period
            """
        ),
        {"fund_id": fund_id},
    ).fetchall()
    return [r[0] for r in rows]


def upsert_backtest_result(
    conn,
    fund_id: int,
    period_start: date,
    period_end: date,
    total_return: float,
    benchmark_return: Optional[float],
    alpha: Optional[float],
    num_positions: int,
) -> None:
    conn.execute(
        text(
            """
            MERGE backtest_results AS target
            USING (SELECT :fund_id AS fund_id, :period_start AS period_start, :period_end AS period_end) AS source
            ON target.fund_id = source.fund_id
               AND target.period_start = source.period_start
               AND target.period_end = source.period_end
            WHEN MATCHED THEN
                UPDATE SET total_return = :total_return,
                           benchmark_return = :benchmark_return,
                           alpha = :alpha,
                           num_positions = :num_positions,
                           computed_at = SYSUTCDATETIME()
            WHEN NOT MATCHED THEN
                INSERT (fund_id, period_start, period_end, total_return, benchmark_return, alpha, num_positions)
                VALUES (:fund_id, :period_start, :period_end, :total_return, :benchmark_return, :alpha, :num_positions);
            """
        ),
        {
            "fund_id": fund_id,
            "period_start": period_start,
            "period_end": period_end,
            "total_return": total_return,
            "benchmark_return": benchmark_return,
            "alpha": alpha,
            "num_positions": num_positions,
        },
    )
    conn.commit()


def _safe_str(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s if s else None
