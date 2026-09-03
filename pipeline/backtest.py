"""Portfolio backtest engine using 13F holdings and yfinance prices."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text

from config import BACKTEST_UNRESOLVED_POLICY, BENCHMARK_TICKER
from db import (
    get_connection,
    get_fund_filing_periods,
    get_fund_holdings_for_period,
    get_funds,
    log_sync_finish,
    log_sync_start,
    upsert_backtest_result,
)

logger = logging.getLogger(__name__)


def _next_quarter_end(report_period: date) -> date:
    """Estimate next quarter end (~90 days after report period)."""
    return report_period + timedelta(days=92)


def _load_prices(conn, tickers: list[str], start: date, end: date) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()

    placeholders = ", ".join(f":t{i}" for i in range(len(tickers)))
    params = {f"t{i}": t for i, t in enumerate(tickers)}
    params["start"] = start
    params["end"] = end

    prices = pd.read_sql(
        text(
            f"""
            SELECT ticker, price_date, COALESCE(adj_close, close_price) AS price
            FROM daily_prices
            WHERE ticker IN ({placeholders})
              AND price_date BETWEEN :start AND :end
            ORDER BY ticker, price_date
            """
        ),
        conn,
        params=params,
    )
    if not prices.empty:
        prices["price_date"] = pd.to_datetime(prices["price_date"]).dt.date
    return prices


def _get_price_at(prices: pd.DataFrame, ticker: str, target: date) -> Optional[float]:
    subset = prices[(prices["ticker"] == ticker) & (prices["price_date"] <= target)]
    if subset.empty:
        return None
    return float(subset.iloc[-1]["price"])


def _get_last_quote(
    prices: pd.DataFrame, ticker: str, target: date
) -> Optional[tuple[date, float]]:
    subset = prices[(prices["ticker"] == ticker) & (prices["price_date"] <= target)]
    if subset.empty:
        return None
    row = subset.iloc[-1]
    return row["price_date"], float(row["price"])


def _load_security_events(
    conn, tickers: list[str], start: date, end: date
) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    placeholders = ", ".join(f":e{i}" for i in range(len(tickers)))
    params = {f"e{i}": ticker for i, ticker in enumerate(tickers)}
    params.update({"start": start, "end": end})
    events = pd.read_sql(
        text(
            f"""
            SELECT UPPER(TRIM(old_ticker)) AS old_ticker, effective_date, event_type,
                   UPPER(TRIM(successor_ticker)) AS successor_ticker,
                   cash_per_share, exchange_ratio
            FROM security_events
            WHERE UPPER(TRIM(old_ticker)) IN ({placeholders})
              AND effective_date > :start
              AND effective_date <= :end
            ORDER BY old_ticker, effective_date
            """
        ),
        conn,
        params=params,
    )
    if not events.empty:
        events["effective_date"] = pd.to_datetime(events["effective_date"]).dt.date
    return events


def _resolve_event_value(
    event,
    prices: pd.DataFrame,
    period_end: date,
) -> Optional[float]:
    """Calculate terminal value per old share from verified event terms."""
    cash = float(event["cash_per_share"]) if pd.notna(event["cash_per_share"]) else 0.0
    ratio = float(event["exchange_ratio"]) if pd.notna(event["exchange_ratio"]) else None
    successor = event["successor_ticker"] if pd.notna(event["successor_ticker"]) else None

    if event["event_type"] in ("cash_merger", "liquidation") and cash > 0:
        return cash
    if event["event_type"] == "ticker_change" and ratio is None:
        ratio = 1.0
    if successor:
        successor_quote = _get_last_quote(prices, str(successor), period_end)
        if successor_quote and ratio is not None:
            return cash + ratio * successor_quote[1]
    return None


def compute_quarter_return(
    conn,
    fund_id: int,
    report_period: date,
    next_report_period: Optional[date] = None,
) -> Optional[dict]:
    """
    Compute a value-weighted buy-and-hold return for a disclosed portfolio.

    A resolved price is either a non-stale end quote or terminal proceeds from a
    verified security_events row. Unresolved positions follow the configured
    zero_cash or renormalize policy and are reported in coverage diagnostics.
    """
    holdings = get_fund_holdings_for_period(conn, fund_id, report_period)
    if holdings.empty:
        return None

    # Filter to equity long positions with valid tickers
    holdings = holdings[
        holdings["ticker"].notna()
        & (holdings["ticker"] != "")
        & (holdings["put_call"].isna() | (holdings["put_call"] == ""))
    ].copy()
    holdings["ticker"] = holdings["ticker"].astype(str).str.strip().str.upper()

    if holdings.empty:
        return None

    period_end = next_report_period or _next_quarter_end(report_period)
    tickers = holdings["ticker"].unique().tolist()

    events = _load_security_events(conn, tickers, report_period, period_end)
    successor_tickers = (
        events["successor_ticker"].dropna().astype(str).unique().tolist()
        if not events.empty
        else []
    )
    all_tickers = list(dict.fromkeys(tickers + successor_tickers))
    # Include prior trading days so weekend/holiday quarter ends have a start quote.
    prices = _load_prices(conn, all_tickers, report_period - timedelta(days=10), period_end)

    total_value = holdings["value_usd"].sum()
    if total_value <= 0:
        return None

    holdings["weight"] = holdings["value_usd"] / total_value

    position_returns = []
    diagnostics = {
        "no_start_price_positions": 0,
        "delisted_positions": 0,
        "resolved_event_positions": 0,
        "unresolved_positions": 0,
    }
    resolved_value = 0.0
    stale_cutoff = period_end - timedelta(days=7)
    for _, row in holdings.iterrows():
        ticker = row["ticker"]
        start_price = _get_price_at(prices, ticker, report_period)
        if not start_price or start_price <= 0:
            diagnostics["no_start_price_positions"] += 1
            diagnostics["unresolved_positions"] += 1
            continue

        end_quote = _get_last_quote(prices, ticker, period_end)
        end_value = None
        resolution = "market_price"
        if end_quote and end_quote[0] >= stale_cutoff:
            end_value = end_quote[1]
        else:
            diagnostics["delisted_positions"] += 1
            ticker_events = (
                events[events["old_ticker"] == ticker] if not events.empty else pd.DataFrame()
            )
            if not ticker_events.empty:
                event = ticker_events.iloc[0]
                end_value = _resolve_event_value(event, prices, period_end)
                if end_value is not None:
                    diagnostics["resolved_event_positions"] += 1
                    resolution = str(event["event_type"])

        if end_value is None:
            diagnostics["unresolved_positions"] += 1
            continue

        ret = (end_value - start_price) / start_price
        resolved_value += float(row["value_usd"])
        position_returns.append(
            {
                "ticker": ticker,
                "weight": row["weight"],
                "return": ret,
                "resolution": resolution,
            }
        )

    price_coverage = resolved_value / float(total_value)
    if position_returns:
        ret_df = pd.DataFrame(position_returns)
        weighted_resolved_return = (ret_df["weight"] * ret_df["return"]).sum()
    else:
        weighted_resolved_return = 0.0
    if BACKTEST_UNRESOLVED_POLICY == "renormalize" and price_coverage > 0:
        portfolio_return = weighted_resolved_return / price_coverage
    else:
        # Unresolved weight is explicitly held at a zero return.
        portfolio_return = weighted_resolved_return

    # Benchmark return
    bench_prices = _load_prices(
        conn, [BENCHMARK_TICKER], report_period - timedelta(days=10), period_end
    )
    bench_start = _get_price_at(bench_prices, BENCHMARK_TICKER, report_period)
    bench_end = _get_price_at(bench_prices, BENCHMARK_TICKER, period_end)
    benchmark_return = None
    alpha = None
    if bench_start and bench_end and bench_start > 0:
        benchmark_return = (bench_end - bench_start) / bench_start
        alpha = portfolio_return - benchmark_return

    return {
        "period_start": report_period,
        "period_end": period_end,
        "total_return": float(portfolio_return),
        "benchmark_return": float(benchmark_return) if benchmark_return is not None else None,
        "alpha": float(alpha) if alpha is not None else None,
        "num_positions": len(position_returns),
        "price_coverage": float(price_coverage),
        "unresolved_policy": BACKTEST_UNRESOLVED_POLICY,
        **diagnostics,
    }


def run_backtest_for_fund(fund_id: int) -> list[dict]:
    """Run backtest across all available filing periods for a fund."""
    results = []
    with get_connection() as conn:
        periods = get_fund_filing_periods(conn, fund_id)
        for index, period in enumerate(periods[:-1]):  # skip latest (no forward period yet)
            result = compute_quarter_return(conn, fund_id, period, periods[index + 1])
            if result:
                upsert_backtest_result(
                    conn,
                    fund_id=fund_id,
                    period_start=result["period_start"],
                    period_end=result["period_end"],
                    total_return=result["total_return"],
                    benchmark_return=result["benchmark_return"],
                    alpha=result["alpha"],
                    num_positions=result["num_positions"],
                )
                logger.info(
                    "Fund %s period %s: return %.2f%%, price coverage %.2f%%, "
                    "%d no-start, %d delisted, %d event-resolved, %d unresolved (%s)",
                    fund_id,
                    period,
                    result["total_return"] * 100,
                    result["price_coverage"] * 100,
                    result["no_start_price_positions"],
                    result["delisted_positions"],
                    result["resolved_event_positions"],
                    result["unresolved_positions"],
                    result["unresolved_policy"],
                )
                results.append(result)
    return results


def run_all_backtests() -> dict:
    stats = {"funds_processed": 0, "periods_computed": 0, "errors": []}

    with get_connection() as conn:
        log_id = log_sync_start(conn, "backtest")
        funds = get_funds(conn)

    for fund in funds:
        try:
            results = run_backtest_for_fund(fund["id"])
            stats["funds_processed"] += 1
            stats["periods_computed"] += len(results)
        except Exception as e:
            stats["errors"].append(f"{fund['name']}: {e}")
            logger.exception("Backtest failed for %s", fund["name"])

    with get_connection() as conn:
        log_sync_finish(
            conn,
            log_id,
            "success" if not stats["errors"] else "failed",
            message=str(stats["errors"][:5]) if stats["errors"] else "OK",
            records_affected=stats["periods_computed"],
        )

    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_all_backtests()
    print(result)
