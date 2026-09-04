"""Download and parse 13F filings from SEC EDGAR."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd
from edgar import Company, set_identity

from config import DEFAULT_QUARTERS_BACK, SEC_IDENTITY
from db import (
    get_filing_holding_status,
    get_connection,
    get_funds,
    insert_filing,
    insert_holdings,
    log_sync_finish,
    log_sync_start,
    seed_funds,
    replace_holdings,
)

logger = logging.getLogger(__name__)


def _parse_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _normalize_holdings_df(df: pd.DataFrame) -> pd.DataFrame:
    """Map edgartools holdings columns to our schema."""
    if df is None or df.empty:
        return pd.DataFrame()

    col_map = {
        "Cusip": "cusip",
        "cusip": "cusip",
        "Ticker": "ticker",
        "ticker": "ticker",
        "Issuer": "issuer_name",
        "issuer": "issuer_name",
        "NameOfIssuer": "issuer_name",
        "nameOfIssuer": "issuer_name",
        "Class": "security_class",
        "TitleOfClass": "security_class",
        "titleOfClass": "security_class",
        "Shares": "shares",
        "SharesPrnAmount": "shares",
        "sshPrnamt": "shares",
        "Value": "value_usd",
        "value": "value_usd",
        "PutCall": "put_call",
        "putCall": "put_call",
        "InvestmentDiscretion": "investment_discretion",
        "investmentDiscretion": "investment_discretion",
    }

    normalized = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    for col in ["cusip", "ticker", "issuer_name", "security_class", "put_call", "investment_discretion"]:
        if col not in normalized.columns:
            normalized[col] = None

    if "shares" in normalized.columns:
        normalized["shares"] = pd.to_numeric(normalized["shares"], errors="coerce").fillna(0).astype(int)
    else:
        normalized["shares"] = 0

    if "value_usd" in normalized.columns:
        normalized["value_usd"] = pd.to_numeric(normalized["value_usd"], errors="coerce").fillna(0).astype(int)
    else:
        normalized["value_usd"] = 0

    # Exclude options for long-only portfolio view (keep in DB but filter in backtest)
    return normalized[
        ["cusip", "ticker", "issuer_name", "security_class", "shares", "value_usd", "put_call", "investment_discretion"]
    ]


def fetch_fund_filings(cik: str, max_filings: int = DEFAULT_QUARTERS_BACK) -> list:
    """Fetch recent 13F-HR filings for a fund by CIK."""
    set_identity(SEC_IDENTITY)
    company = Company(cik)
    filings = company.get_filings(form="13F-HR")
    return list(filings[:max_filings])


def process_filing(fund_id: int, filing) -> tuple[int, int]:
    """Parse one filing and persist to database. Returns (filing_id, holdings_count)."""
    accession_no = filing.accession_no

    with get_connection() as conn:
        existing = get_filing_holding_status(conn, accession_no)
        if existing and existing["holding_rows"] > 0 and existing["invalid_share_rows"] == 0:
            logger.info("Skipping existing filing %s", accession_no)
            return 0, 0

    thirteenf = filing.obj()
    holdings_df = _normalize_holdings_df(thirteenf.infotable if hasattr(thirteenf, "infotable") else thirteenf.holdings)

    report_period = _parse_date(getattr(thirteenf, "report_period", None))
    filing_date = _parse_date(getattr(filing, "filing_date", None))
    total_value = getattr(thirteenf, "total_value", None)
    total_holdings = getattr(thirteenf, "total_holdings", None) or len(holdings_df)

    if total_value is not None:
        total_value = int(total_value)

    with get_connection() as conn:
        if existing:
            if not holdings_df.empty and not (holdings_df["shares"] > 0).any():
                raise ValueError(
                    f"Parsed filing {accession_no} still contains no positive share counts"
                )
            count = replace_holdings(conn, existing["id"], fund_id, holdings_df)
            logger.info("Repaired %d holdings for existing filing %s", count, accession_no)
            return existing["id"], count

        filing_id = insert_filing(
            conn,
            fund_id=fund_id,
            accession_no=accession_no,
            report_period=report_period,
            filing_date=filing_date,
            total_value=total_value,
            total_holdings=total_holdings,
        )
        count = insert_holdings(conn, filing_id, fund_id, holdings_df)
        return filing_id, count


def sync_all_funds(max_filings: int = DEFAULT_QUARTERS_BACK) -> dict:
    """Download 13F data for all funds in the database."""
    set_identity(SEC_IDENTITY)
    stats = {
        "funds_processed": 0,
        "funds_with_zero_filings": [],
        "filings_added": 0,
        "holdings_added": 0,
        "errors": [],
    }

    with get_connection() as conn:
        log_id = log_sync_start(conn, "edgar_13f")
        seed_funds(conn)
        funds = get_funds(conn)

    for fund in funds:
        cik = fund.get("cik")
        if not cik:
            stats["errors"].append(f"No CIK for {fund['name']}")
            continue

        try:
            filings = fetch_fund_filings(cik, max_filings)
            stats["funds_processed"] += 1

            if not filings:
                message = f"{fund['name']} returned no 13F-HR filings for the requested {max_filings} quarters"
                stats["funds_with_zero_filings"].append(fund["name"])
                stats["errors"].append(message)
                logger.warning(message)
                continue

            for filing in filings:
                try:
                    filing_id, count = process_filing(fund["id"], filing)
                    if filing_id:
                        stats["filings_added"] += 1
                        stats["holdings_added"] += count
                except Exception as e:
                    stats["errors"].append(f"{fund['name']} filing {filing.accession_no}: {e}")
                    logger.exception("Error processing filing")

        except Exception as e:
            stats["errors"].append(f"{fund['name']}: {e}")
            logger.exception("Error fetching filings for %s", fund["name"])

    with get_connection() as conn:
        status = "success" if not stats["errors"] else "failed"
        log_sync_finish(
            conn,
            log_id,
            status,
            message=str(stats["errors"][:5]) if stats["errors"] else "OK",
            records_affected=stats["holdings_added"],
        )

    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = sync_all_funds()
    print(result)
