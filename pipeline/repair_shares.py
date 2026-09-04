#!/usr/bin/env python3
"""Audit and automatically repair 13F filings with missing share counts."""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd
from edgar import Company, set_identity
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from config import SEC_IDENTITY
from db import get_connection, get_engine, replace_holdings
from edgar_13f import _normalize_holdings_df
from summaries import refresh_position_summaries

logger = logging.getLogger(__name__)
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "share_repair"
PENDING_ANALYTICS = OUTPUT_DIR / "pending-analytics.json"


def _save_pending(fund_ids: set[int]) -> None:
    PENDING_ANALYTICS.write_text(json.dumps(sorted(fund_ids)),encoding="utf-8")


def _load_pending() -> set[int]:
    if PENDING_ANALYTICS.exists():
        return {int(value) for value in json.loads(PENDING_ANALYTICS.read_text(encoding="utf-8"))}
    # Recover work from runs made before the checkpoint file was introduced.
    prior_report=OUTPUT_DIR/"repair-report.json"
    if prior_report.exists():
        rows=json.loads(prior_report.read_text(encoding="utf-8"))
        pending={int(row["fund_id"]) for row in rows if row.get("status")=="repaired"}
        _save_pending(pending)
        return pending
    return set()


def defective_filings(since: date | None = None, limit: int | None = None) -> list[dict]:
    sql = """
        SELECT f.id filing_id,f.fund_id,fu.name fund_name,fu.cik,f.accession_no,
               f.report_period,f.filing_date,COUNT(h.id) holding_rows,
               SUM(CASE WHEN h.value_usd>0 AND h.shares<=0 THEN 1 ELSE 0 END) invalid_rows,
               SUM(h.value_usd) stored_value,
               COUNT(DISTINCT CASE WHEN h.cusip IS NOT NULL THEN UPPER(TRIM(h.cusip)) END) cusips
        FROM filings f JOIN funds fu ON fu.id=f.fund_id JOIN holdings h ON h.filing_id=f.id
        WHERE (:since IS NULL OR f.report_period>=:since)
        GROUP BY f.id,f.fund_id,fu.name,fu.cik,f.accession_no,f.report_period,f.filing_date
        HAVING SUM(CASE WHEN h.value_usd>0 AND h.shares<=0 THEN 1 ELSE 0 END)>0
        ORDER BY f.report_period DESC,fu.name
    """
    with get_connection() as conn:
        rows=[dict(row) for row in conn.execute(text(sql),{"since":since}).mappings()]
    return rows[:limit] if limit else rows


def _find_filings(cik: str, accessions: set[str]) -> dict[str, object]:
    found={}
    for filing in Company(cik).get_filings(form="13F-HR"):
        if filing.accession_no in accessions:
            found[filing.accession_no]=filing
            if len(found)==len(accessions): break
    return found


def _validate(conn, record: dict, normalized: pd.DataFrame) -> dict:
    invalid=int(((normalized["value_usd"]>0)&(normalized["shares"]<=0)).sum())
    downloaded={str(value).strip().upper() for value in normalized["cusip"].dropna() if str(value).strip()}
    stored={str(row[0]).strip().upper() for row in conn.execute(
        text("SELECT DISTINCT cusip FROM holdings WHERE filing_id=:id AND cusip IS NOT NULL"),
        {"id":record["filing_id"]})}
    overlap=len(downloaded & stored)/max(1,len(stored))
    return {
        "downloaded_rows":len(normalized),"invalid_downloaded_rows":invalid,
        "downloaded_value":int(normalized["value_usd"].sum()),"cusip_overlap":overlap,
        "valid":len(normalized)>0 and invalid==0 and overlap>=0.8,
    }


def _with_db_retry(operation, label: str, attempts: int = 4):
    """Retry one idempotent filing operation after transient Azure disconnects."""
    for attempt in range(1, attempts + 1):
        try:
            with get_connection() as conn:
                return operation(conn)
        except OperationalError:
            get_engine().dispose()
            if attempt == attempts:
                raise
            delay = min(attempt * 5, 15)
            logger.warning(
                "%s lost its Azure SQL connection (attempt %d/%d); retrying in %ds",
                label, attempt, attempts, delay,
            )
            time.sleep(delay)


def _with_task_retry(operation, label: str, attempts: int = 4):
    """Retry an idempotent task that manages its own database connections."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except OperationalError:
            get_engine().dispose()
            if attempt == attempts:
                raise
            delay = min(attempt * 5, 15)
            logger.warning(
                "%s lost its Azure SQL connection (attempt %d/%d); retrying in %ds",
                label, attempt, attempts, delay,
            )
            time.sleep(delay)


def main() -> int:
    parser=argparse.ArgumentParser(description="Repair missing SEC 13F share counts")
    parser.add_argument("--dry-run",action="store_true",help="Audit only; do not download or update")
    parser.add_argument("--since",type=date.fromisoformat,help="Only repair periods on/after YYYY-MM-DD")
    parser.add_argument("--limit",type=int,help="Maximum filings to process")
    parser.add_argument("--skip-analytics",action="store_true",help="Skip backtest/trade-copy refresh")
    args=parser.parse_args()
    records=defective_filings(args.since,args.limit)
    print(f"Found {len(records)} defective filings.")
    if args.dry_run:
        for row in records:
            print(f"{row['report_period']} | {row['fund_name']} | {row['accession_no']} | {row['invalid_rows']}/{row['holding_rows']} invalid")
        return 0

    set_identity(SEC_IDENTITY)
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    report=[]; repaired_funds=_load_pending()
    by_cik={}
    for row in records: by_cik.setdefault(str(row["cik"]),[]).append(row)
    for cik,cik_records in by_cik.items():
        filings=_find_filings(cik,{row["accession_no"] for row in cik_records})
        for record in cik_records:
            result={**record,"status":"failed"}
            try:
                filing=filings.get(record["accession_no"])
                if filing is None: raise RuntimeError("filing not found on EDGAR")
                filing_object=filing.obj()
                raw=filing_object.infotable if hasattr(filing_object,"infotable") else filing_object.holdings
                normalized=_normalize_holdings_df(raw.copy())
                prefix=f"{record['report_period']}-{record['accession_no']}"
                raw.to_csv(OUTPUT_DIR/f"{prefix}-raw.csv",index=False)
                normalized.to_csv(OUTPUT_DIR/f"{prefix}-normalized.csv",index=False)
                validation=_with_db_retry(
                    lambda conn:_validate(conn,record,normalized),
                    f"Validate {record['accession_no']}",
                )
                result.update(validation)
                if not validation["valid"]: raise ValueError(f"validation failed: {validation}")
                _with_db_retry(
                    lambda conn:replace_holdings(
                        conn,record["filing_id"],record["fund_id"],normalized
                    ),
                    f"Replace {record['accession_no']}",
                )
                result["status"]="repaired"; repaired_funds.add(record["fund_id"])
                _save_pending(repaired_funds)
                print(f"Repaired {record['fund_name']} {record['report_period']} ({len(normalized)} rows)")
            except Exception as exc:
                result["error"]=str(exc); logger.exception("Could not repair %s",record["accession_no"])
            report.append(result)

    (OUTPUT_DIR/"repair-report.json").write_text(json.dumps(report,default=str,indent=2),encoding="utf-8")
    if repaired_funds:
        print("Refreshing persisted position summaries...")
        _with_task_retry(refresh_position_summaries,"Refresh position summaries")
        if not args.skip_analytics:
            from backtest import run_backtest_for_fund
            from trade_copy import run_trade_copy_for_fund
            for fund_id in sorted(repaired_funds):
                print(f"Refreshing analytics for fund {fund_id}...")
                _with_task_retry(
                    lambda fund_id=fund_id:run_backtest_for_fund(fund_id),
                    f"Backtest fund {fund_id}",
                )
                _with_task_retry(
                    lambda fund_id=fund_id:run_trade_copy_for_fund(fund_id),
                    f"Trade-copy fund {fund_id}",
                )
                repaired_funds.discard(fund_id)
                _save_pending(repaired_funds)
    failed=sum(row["status"]!="repaired" for row in report)
    print(f"Complete: {len(report)-failed} repaired, {failed} failed. Report: {OUTPUT_DIR/'repair-report.json'}")
    return 1 if failed else 0


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s")
    raise SystemExit(main())
