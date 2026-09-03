"""Investable 13F trade-copy simulation using post-filing closing prices."""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
from sqlalchemy import text

from backtest import _load_prices, _load_security_events
from config import (
    BENCHMARK_TICKER,
    TRADE_COPY_COST_BPS,
    TRADE_COPY_UNRESOLVED_POLICY,
    TRADE_COPY_WEIGHT_CHANGE_THRESHOLD,
)
from db import get_connection, get_funds, log_sync_finish, log_sync_start

logger = logging.getLogger(__name__)
MAX_PLAUSIBLE_QUARTERLY_RETURN = 10.0


def _filing_sequence(conn, fund_id: int) -> list[dict[str, Any]]:
    """Use the earliest public filing for each report period; ignore later amendments."""
    rows = conn.execute(
        text(
            """
            WITH ranked AS (
                SELECT id, fund_id, report_period, filing_date,
                       ROW_NUMBER() OVER (
                           PARTITION BY fund_id, report_period
                           ORDER BY filing_date, id
                       ) AS rn
                FROM filings
                WHERE fund_id = :fund_id AND form_type = '13F-HR'
            )
            SELECT id, report_period, filing_date
            FROM ranked
            WHERE rn = 1
            ORDER BY report_period
            """
        ),
        {"fund_id": fund_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _holdings_for_filing(conn, filing_id: int) -> pd.DataFrame:
    return pd.read_sql(
        text(
            """
            SELECT UPPER(TRIM(ticker)) AS ticker, MAX(cusip) AS cusip,
                   SUM(value_usd) AS disclosed_value
            FROM holdings
            WHERE filing_id = :filing_id
              AND ticker IS NOT NULL AND TRIM(ticker) <> ''
              AND (put_call IS NULL OR put_call = '')
            GROUP BY UPPER(TRIM(ticker))
            ORDER BY disclosed_value DESC
            """
        ),
        conn,
        params={"filing_id": filing_id},
    )


def _first_quote_after(
    prices: pd.DataFrame, ticker: str, target: date
) -> Optional[tuple[date, float]]:
    subset = prices[(prices["ticker"] == ticker) & (prices["price_date"] > target)]
    if subset.empty:
        return None
    row = subset.iloc[0]
    return row["price_date"], float(row["price"])


def _last_quote_before(
    prices: pd.DataFrame, ticker: str, target: date
) -> Optional[tuple[date, float]]:
    subset = prices[(prices["ticker"] == ticker) & (prices["price_date"] <= target)]
    if subset.empty:
        return None
    row = subset.iloc[-1]
    return row["price_date"], float(row["price"])


def _event_exit_value(event, prices: pd.DataFrame, exit_signal_date: date):
    cash = float(event["cash_per_share"]) if pd.notna(event["cash_per_share"]) else 0.0
    ratio = float(event["exchange_ratio"]) if pd.notna(event["exchange_ratio"]) else None
    successor = event["successor_ticker"] if pd.notna(event["successor_ticker"]) else None
    event_type = str(event["event_type"])
    if event_type in ("cash_merger", "liquidation") and cash > 0:
        return event["effective_date"], cash
    if event_type == "ticker_change" and ratio is None:
        ratio = 1.0
    if successor and ratio is not None:
        quote = _first_quote_after(prices, str(successor), exit_signal_date)
        if quote:
            return quote[0], cash + ratio * quote[1]
    return None


def _weights(holdings: pd.DataFrame) -> dict[str, float]:
    if holdings.empty:
        return {}
    total = float(holdings["disclosed_value"].sum())
    if total <= 0:
        return {}
    return {
        str(row.ticker): float(row.disclosed_value) / total
        for row in holdings.itertuples()
    }


def _turnover(current: dict[str, float], previous: dict[str, float]) -> float:
    if not previous:
        return 1.0
    names = set(current) | set(previous)
    return 0.5 * sum(abs(current.get(t, 0.0) - previous.get(t, 0.0)) for t in names)


def _trade_type(weight: float, previous_weight: float) -> str:
    if previous_weight == 0:
        return "new_buy"
    change = weight - previous_weight
    if change >= TRADE_COPY_WEIGHT_CHANGE_THRESHOLD:
        return "increase"
    if change <= -TRADE_COPY_WEIGHT_CHANGE_THRESHOLD:
        return "decrease"
    return "unchanged"


def _persist_result(conn, aggregate: dict, positions: list[dict]) -> int:
    result = conn.execute(
        text(
            """
            MERGE trade_copy_results AS target
            USING (SELECT :fund_id AS fund_id, :signal_filing_id AS signal_filing_id) AS source
            ON target.fund_id = source.fund_id
               AND target.signal_filing_id = source.signal_filing_id
            WHEN MATCHED THEN UPDATE SET
                next_filing_id=:next_filing_id, signal_date=:signal_date,
                entry_date=:entry_date, exit_date=:exit_date,
                total_return=:total_return, benchmark_return=:benchmark_return,
                alpha=:alpha, turnover=:turnover, transaction_cost=:transaction_cost,
                price_coverage=:price_coverage, unresolved_policy=:unresolved_policy,
                num_positions=:num_positions,
                no_start_price_positions=:no_start_price_positions,
                delisted_positions=:delisted_positions,
                resolved_event_positions=:resolved_event_positions,
                unresolved_positions=:unresolved_positions,
                computed_at=SYSUTCDATETIME()
            WHEN NOT MATCHED THEN INSERT
                (fund_id, signal_filing_id, next_filing_id, signal_date, entry_date, exit_date,
                 total_return, benchmark_return, alpha, turnover, transaction_cost,
                 price_coverage, unresolved_policy, num_positions,
                 no_start_price_positions, delisted_positions,
                 resolved_event_positions, unresolved_positions)
            VALUES
                (:fund_id, :signal_filing_id, :next_filing_id, :signal_date, :entry_date, :exit_date,
                 :total_return, :benchmark_return, :alpha, :turnover, :transaction_cost,
                 :price_coverage, :unresolved_policy, :num_positions,
                 :no_start_price_positions, :delisted_positions,
                 :resolved_event_positions, :unresolved_positions)
            OUTPUT INSERTED.id;
            """
        ),
        aggregate,
    )
    result_id = int(result.scalar_one())
    conn.execute(
        text("DELETE FROM trade_copy_position_results WHERE trade_copy_result_id=:id"),
        {"id": result_id},
    )
    if positions:
        for row in positions:
            row["trade_copy_result_id"] = result_id
        conn.execute(
            text(
                """
                INSERT INTO trade_copy_position_results
                    (trade_copy_result_id, fund_id, signal_filing_id, ticker, cusip,
                     position_rank, disclosed_value, target_weight, previous_weight,
                     weight_change, trade_type, entry_date, entry_price, exit_date,
                     exit_value, total_return, benchmark_return, excess_return,
                     contribution, resolution_type, is_resolved, resolution_note)
                VALUES
                    (:trade_copy_result_id, :fund_id, :signal_filing_id, :ticker, :cusip,
                     :position_rank, :disclosed_value, :target_weight, :previous_weight,
                     :weight_change, :trade_type, :entry_date, :entry_price, :exit_date,
                     :exit_value, :total_return, :benchmark_return, :excess_return,
                     :contribution, :resolution_type, :is_resolved, :resolution_note)
                """
            ),
            positions,
        )
    conn.commit()
    return result_id


def simulate_period(conn, fund_id: int, signal: dict, next_signal: dict, previous: dict) -> Optional[dict]:
    holdings = _holdings_for_filing(conn, signal["id"])
    current = _weights(holdings)
    if not current:
        return None

    signal_date = signal["filing_date"]
    exit_signal_date = next_signal["filing_date"]
    tickers = list(current)
    events = _load_security_events(conn, tickers, signal_date, exit_signal_date)
    successors = events["successor_ticker"].dropna().astype(str).unique().tolist() if not events.empty else []
    prices = _load_prices(
        conn,
        list(dict.fromkeys(tickers + successors + [BENCHMARK_TICKER])),
        signal_date + timedelta(days=1),
        exit_signal_date + timedelta(days=10),
    )
    benchmark_entry = _first_quote_after(prices, BENCHMARK_TICKER, signal_date)
    benchmark_exit = _first_quote_after(prices, BENCHMARK_TICKER, exit_signal_date)
    if not benchmark_entry or not benchmark_exit:
        logger.warning("Skipping fund %s filing %s: missing benchmark dates", fund_id, signal["id"])
        return None
    benchmark_return = (benchmark_exit[1] - benchmark_entry[1]) / benchmark_entry[1]

    total_value = float(holdings["disclosed_value"].sum())
    resolved_value = 0.0
    weighted_return = 0.0
    diagnostics = {
        "no_start_price_positions": 0,
        "delisted_positions": 0,
        "resolved_event_positions": 0,
        "unresolved_positions": 0,
    }
    positions = []
    for rank, row in enumerate(holdings.itertuples(), start=1):
        ticker = str(row.ticker)
        weight = current[ticker]
        old_weight = previous.get(ticker, 0.0)
        entry = _first_quote_after(prices, ticker, signal_date)
        exit_quote = _first_quote_after(prices, ticker, exit_signal_date)
        resolution = "market_price"
        note = None
        terminal = exit_quote

        if not entry:
            diagnostics["no_start_price_positions"] += 1
            diagnostics["unresolved_positions"] += 1
            resolution = "no_start_price"
        else:
            last_old_quote = _last_quote_before(prices, ticker, exit_signal_date + timedelta(days=10))
            appears_delisted = not exit_quote or (
                last_old_quote and last_old_quote[0] < exit_signal_date - timedelta(days=7)
            )
            if appears_delisted:
                diagnostics["delisted_positions"] += 1
                terminal = None
                ticker_events = events[events["old_ticker"] == ticker] if not events.empty else pd.DataFrame()
                if not ticker_events.empty:
                    event = ticker_events.iloc[0]
                    terminal = _event_exit_value(event, prices, exit_signal_date)
                    if terminal:
                        diagnostics["resolved_event_positions"] += 1
                        resolution = str(event["event_type"])
                if terminal is None:
                    diagnostics["unresolved_positions"] += 1
                    resolution = "unresolved_delisting"
                    note = "No verified security_events terms"

        position_return = None
        excess_return = None
        contribution = None
        if entry and terminal:
            position_return = (terminal[1] - entry[1]) / entry[1]
            if position_return > MAX_PLAUSIBLE_QUARTERLY_RETURN or position_return < -1.0:
                note = f"Rejected implausible price return {position_return:.2f}; probable ticker reuse or bad price history"
                resolution = "invalid_price_history"
                diagnostics["unresolved_positions"] += 1
                position_return = None
                terminal = None
            else:
                excess_return = position_return - benchmark_return
                contribution = weight * position_return
                weighted_return += contribution
                resolved_value += float(row.disclosed_value)

        positions.append(
            {
                "fund_id": fund_id,
                "signal_filing_id": signal["id"],
                "ticker": ticker,
                "cusip": row.cusip,
                "position_rank": rank,
                "disclosed_value": int(row.disclosed_value),
                "target_weight": weight,
                "previous_weight": old_weight,
                "weight_change": weight - old_weight,
                "trade_type": _trade_type(weight, old_weight),
                "entry_date": entry[0] if entry else None,
                "entry_price": entry[1] if entry else None,
                "exit_date": terminal[0] if terminal else None,
                "exit_value": terminal[1] if terminal else None,
                "total_return": position_return,
                "benchmark_return": benchmark_return if position_return is not None else None,
                "excess_return": excess_return,
                "contribution": contribution,
                "resolution_type": resolution,
                "is_resolved": position_return is not None,
                "resolution_note": note,
            }
        )

    coverage = resolved_value / total_value
    if TRADE_COPY_UNRESOLVED_POLICY == "renormalize" and coverage > 0:
        gross_return = weighted_return / coverage
    else:
        gross_return = weighted_return
    turnover = _turnover(current, previous)
    transaction_cost = turnover * TRADE_COPY_COST_BPS / 10000.0
    total_return = gross_return - transaction_cost
    aggregate = {
        "fund_id": fund_id,
        "signal_filing_id": signal["id"],
        "next_filing_id": next_signal["id"],
        "signal_date": signal_date,
        "entry_date": benchmark_entry[0],
        "exit_date": benchmark_exit[0],
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "alpha": total_return - benchmark_return,
        "turnover": turnover,
        "transaction_cost": transaction_cost,
        "price_coverage": coverage,
        "unresolved_policy": TRADE_COPY_UNRESOLVED_POLICY,
        "num_positions": len(positions),
        **diagnostics,
    }
    _persist_result(conn, aggregate, positions)
    return aggregate


def run_trade_copy_for_fund(fund_id: int) -> list[dict]:
    results = []
    with get_connection() as conn:
        filings = _filing_sequence(conn, fund_id)
        previous = {}
        for index in range(len(filings) - 1):
            signal = filings[index]
            next_signal = filings[index + 1]
            result = simulate_period(conn, fund_id, signal, next_signal, previous)
            current_holdings = _holdings_for_filing(conn, signal["id"])
            previous = _weights(current_holdings)
            if result:
                results.append(result)
                logger.info(
                    "Fund %s filing %s: copy return %.2f%%, alpha %.2f%%, coverage %.2f%%",
                    fund_id,
                    signal["id"],
                    result["total_return"] * 100,
                    result["alpha"] * 100,
                    result["price_coverage"] * 100,
                )
    return results


def run_all_trade_copy() -> dict:
    stats = {"funds_processed": 0, "periods_computed": 0, "errors": []}
    with get_connection() as conn:
        log_id = log_sync_start(conn, "trade_copy")
        funds = get_funds(conn)
    for fund in funds:
        try:
            results = run_trade_copy_for_fund(fund["id"])
            stats["funds_processed"] += 1
            stats["periods_computed"] += len(results)
        except Exception as exc:
            stats["errors"].append(f"{fund['name']}: {exc}")
            logger.exception("Trade-copy simulation failed for %s", fund["name"])
    with get_connection() as conn:
        log_sync_finish(
            conn,
            log_id,
            "success" if not stats["errors"] else "failed",
            str(stats["errors"][:5]) if stats["errors"] else "OK",
            stats["periods_computed"],
        )
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Run trade-copy simulations")
    parser.add_argument("--fund-id", type=int, help="Recompute only one fund")
    args = parser.parse_args()
    print(run_trade_copy_for_fund(args.fund_id) if args.fund_id else run_all_trade_copy())
