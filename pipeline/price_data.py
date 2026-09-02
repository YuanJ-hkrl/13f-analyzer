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
    get_tickers_with_first_appearance,
    log_sync_finish,
    log_sync_start,
    upsert_daily_prices,
)
from extract_securities import sync_securities

logger = logging.getLogger(__name__)


def fetch_ticker_prices(
    ticker: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """Download close-price history for a single ticker."""
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
            "Close": "close_price",
            "Adj Close": "adj_close",
        }
    )
    df["price_date"] = pd.to_datetime(df["price_date"]).dt.date

    cols = ["ticker", "price_date", "close_price", "adj_close"]
    return df[[c for c in cols if c in df.columns]]


def sync_prices(
    tickers: Optional[list[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    include_benchmark: bool = True,
) -> dict:
    """Sync price data for all tickers found in holdings (+ benchmark)."""
    stats = {
        "tickers_total": 0,
        "tickers_processed": 0,
        "tickers_missing": 0,
        "rows_upserted": 0,
        "errors": [],
    }

    # Refresh security metadata so every ticker has its earliest 13F report date.
    sync_securities()

    with get_connection() as conn:
        log_id = log_sync_start(conn, "price_data")
        first_appearances = get_tickers_with_first_appearance(conn)
        if tickers is None:
            tickers = list(first_appearances)

    if include_benchmark and BENCHMARK_TICKER not in tickers:
        tickers = [BENCHMARK_TICKER] + tickers

    tickers = [ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()]
    stats["tickers_total"] = len(tickers)

    requested_end = end_date or date.today()
    earliest_appearance = min(first_appearances.values(), default=None)
    logger.info(
        "Preparing to download %d tickers through %s; each ticker starts at its "
        "first 13F appearance",
        len(tickers),
        requested_end,
    )

    for position, ticker in enumerate(tickers, start=1):
        ticker_start = start_date or first_appearances.get(ticker)
        if ticker == BENCHMARK_TICKER and ticker_start is None:
            ticker_start = earliest_appearance
        if ticker_start is None:
            ticker_start = requested_end - timedelta(days=365 * 3)
            logger.warning(
                "No first 13F appearance stored for %s; falling back to %s",
                ticker,
                ticker_start,
            )
        logger.info(
            "[%d/%d] Downloading %s from first 13F appearance %s",
            position,
            len(tickers),
            ticker,
            ticker_start,
        )
        try:
            prices = fetch_ticker_prices(ticker, ticker_start, requested_end)
            if prices.empty:
                stats["tickers_missing"] += 1
                stats["errors"].append(f"No data for {ticker}")
                logger.warning(
                    "[%d/%d] No price data found for %s; continuing with the next ticker",
                    position,
                    len(tickers),
                    ticker,
                )
                continue

            first_price_date = prices["price_date"].min()
            last_price_date = prices["price_date"].max()
            with get_connection() as conn:
                count = upsert_daily_prices(conn, prices)
                stats["rows_upserted"] += count
                stats["tickers_processed"] += 1
            logger.info(
                "[%d/%d] Completed %s: %d rows, first day %s, last day %s "
                "(%d/%d tickers completed)",
                position,
                len(tickers),
                ticker,
                count,
                first_price_date,
                last_price_date,
                stats["tickers_processed"],
                len(tickers),
            )

        except Exception as e:
            stats["errors"].append(f"{ticker}: {e}")
            logger.exception(
                "[%d/%d] Error syncing %s; continuing with the next ticker",
                position,
                len(tickers),
                ticker,
            )

    with get_connection() as conn:
        log_sync_finish(
            conn,
            log_id,
            "success" if not stats["errors"] else "failed",
            message=str(stats["errors"][:5]) if stats["errors"] else "OK",
            records_affected=stats["rows_upserted"],
        )

    logger.info(
        "Price sync finished: %d/%d tickers completed, %d returned no data, "
        "%d rows upserted, %d total errors",
        stats["tickers_processed"],
        stats["tickers_total"],
        stats["tickers_missing"],
        stats["rows_upserted"],
        len(stats["errors"]),
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
