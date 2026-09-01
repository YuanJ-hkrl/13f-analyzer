"""Download stock price data via yfinance."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from config import BENCHMARK_TICKER
from db import (
    get_connection,
    get_distinct_tickers,
    log_sync_finish,
    log_sync_start,
    upsert_daily_prices,
)

logger = logging.getLogger(__name__)


def fetch_ticker_prices(
    ticker: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """Download OHLCV data for a single ticker."""
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=365 * 3)

    try:
        data = yf.download(
            ticker,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            progress=False,
        )
    except Exception as e:
        logger.warning("Failed to download %s: %s", ticker, e)
        return pd.DataFrame()

    if data.empty:
        return pd.DataFrame()

    # yfinance may return MultiIndex columns for single ticker in some versions
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    df = data.reset_index()
    df["ticker"] = ticker
    df = df.rename(
        columns={
            "Date": "price_date",
            "Open": "open_price",
            "High": "high_price",
            "Low": "low_price",
            "Close": "close_price",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )
    df["price_date"] = pd.to_datetime(df["price_date"]).dt.date

    cols = ["ticker", "price_date", "open_price", "high_price", "low_price", "close_price", "adj_close", "volume"]
    return df[[c for c in cols if c in df.columns]]


def sync_prices(
    tickers: Optional[list[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    include_benchmark: bool = True,
) -> dict:
    """Sync price data for all tickers found in holdings (+ benchmark)."""
    stats = {"tickers_processed": 0, "rows_upserted": 0, "errors": []}

    with get_connection() as conn:
        log_id = log_sync_start(conn, "price_data")
        if tickers is None:
            tickers = get_distinct_tickers(conn)

    if include_benchmark and BENCHMARK_TICKER not in tickers:
        tickers = [BENCHMARK_TICKER] + tickers

    for ticker in tickers:
        if not ticker or ticker.strip() == "":
            continue
        try:
            prices = fetch_ticker_prices(ticker.strip().upper(), start_date, end_date)
            if prices.empty:
                stats["errors"].append(f"No data for {ticker}")
                continue

            with get_connection() as conn:
                count = upsert_daily_prices(conn, prices)
                stats["rows_upserted"] += count
                stats["tickers_processed"] += 1

        except Exception as e:
            stats["errors"].append(f"{ticker}: {e}")
            logger.exception("Error syncing prices for %s", ticker)

    with get_connection() as conn:
        log_sync_finish(
            conn,
            log_id,
            "success" if not stats["errors"] else "failed",
            message=str(stats["errors"][:5]) if stats["errors"] else "OK",
            records_affected=stats["rows_upserted"],
        )

    return stats


def get_price_on_date(conn, ticker: str, target_date: date) -> Optional[float]:
    """Get adjusted close price on or before target_date."""
    row = conn.execute(
        __import__("sqlalchemy").text(
            """
            SELECT TOP 1 COALESCE(adj_close, close_price) AS price
            FROM daily_prices
            WHERE ticker = :ticker AND price_date <= :target_date
            ORDER BY price_date DESC
            """
        ),
        {"ticker": ticker, "target_date": target_date},
    ).first()
    return float(row[0]) if row else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = sync_prices()
    print(result)
