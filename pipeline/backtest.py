"""Portfolio backtest engine using 13F holdings and yfinance prices."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text

from config import BENCHMARK_TICKER
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

    return pd.read_sql(
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


def _get_price_at(prices: pd.DataFrame, ticker: str, target: date) -> Optional[float]:
    subset = prices[(prices["ticker"] == ticker) & (prices["price_date"] <= target)]
    if subset.empty:
        return None
    return float(subset.iloc[-1]["price"])


def compute_quarter_return(
    conn,
    fund_id: int,
    report_period: date,
) -> Optional[dict]:
    """
    Compute buy-and-hold return for a fund's disclosed portfolio from
    report_period to next quarter end, using equal-weighted position returns.
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

    if holdings.empty:
        return None

    period_end = _next_quarter_end(report_period)
    tickers = holdings["ticker"].unique().tolist()

    prices = _load_prices(conn, tickers, report_period, period_end)
    if prices.empty:
        return None

    total_value = holdings["value_usd"].sum()
    if total_value <= 0:
        return None

    holdings["weight"] = holdings["value_usd"] / total_value

    position_returns = []
    for _, row in holdings.iterrows():
        ticker = row["ticker"]
        start_price = _get_price_at(prices, ticker, report_period)
        end_price = _get_price_at(prices, ticker, period_end)
        if start_price and end_price and start_price > 0:
            ret = (end_price - start_price) / start_price
            position_returns.append({"ticker": ticker, "weight": row["weight"], "return": ret})

    if not position_returns:
        return None

    ret_df = pd.DataFrame(position_returns)
    portfolio_return = (ret_df["weight"] * ret_df["return"]).sum()

    # Benchmark return
    bench_prices = _load_prices(conn, [BENCHMARK_TICKER], report_period, period_end)
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
    }


def run_backtest_for_fund(fund_id: int) -> list[dict]:
    """Run backtest across all available filing periods for a fund."""
    results = []
    with get_connection() as conn:
        periods = get_fund_filing_periods(conn, fund_id)
        for period in periods[:-1]:  # skip latest (no forward period yet)
            result = compute_quarter_return(conn, fund_id, period)
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
