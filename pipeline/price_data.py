"""Download stock price data via yfinance."""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from hashlib import sha1
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from config import (
    BENCHMARK_TICKER,
    PRICE_CACHE_DIR,
    PRICE_DOWNLOAD_WORKERS,
    PRICE_UPLOAD_BATCH_SIZE,
)
from db import (
    get_connection,
    get_tickers_with_first_appearance,
    log_sync_finish,
    log_sync_start,
    upsert_daily_prices,
)
from extract_securities import sync_securities

logger = logging.getLogger(__name__)


def _cache_path(ticker: str, start_date: date, end_date: date) -> Path:
    """Return a Windows-safe, range-specific cache path for a ticker."""
    safe_ticker = re.sub(r"[^A-Za-z0-9._-]+", "_", ticker).strip("._") or "ticker"
    digest = sha1(ticker.encode("utf-8")).hexdigest()[:8]
    return PRICE_CACHE_DIR / (
        f"{safe_ticker}_{digest}_{start_date.isoformat()}_{end_date.isoformat()}.csv"
    )


def _load_cached_prices(path: Path) -> pd.DataFrame:
    prices = pd.read_csv(path)
    required = {"ticker", "price_date", "close_price"}
    if not required.issubset(prices.columns):
        raise ValueError(f"Cache file is missing required columns: {path}")
    prices["price_date"] = pd.to_datetime(prices["price_date"]).dt.date
    return prices


def _download_or_load_cache(
    ticker: str,
    start_date: date,
    end_date: date,
) -> tuple[str, pd.DataFrame, bool, Path]:
    """Return ticker prices and whether they came from an existing cache file."""
    cache_path = _cache_path(ticker, start_date, end_date)
    if cache_path.exists():
        try:
            return ticker, _load_cached_prices(cache_path), True, cache_path
        except Exception:
            logger.warning("Ignoring unreadable cache file %s", cache_path, exc_info=True)

    prices = fetch_ticker_prices(ticker, start_date, end_date)
    if not prices.empty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
        prices.to_csv(temporary_path, index=False)
        os.replace(temporary_path, cache_path)
    return ticker, prices, False, cache_path


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
            threads=False,
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
        "tickers_cached": 0,
        "tickers_downloaded": 0,
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
        "Preparing %d tickers through %s using %d parallel download workers; "
        "each ticker starts at its first 13F appearance",
        len(tickers),
        requested_end,
        PRICE_DOWNLOAD_WORKERS,
    )

    download_jobs = []
    for ticker in tickers:
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
        download_jobs.append((ticker, ticker_start, requested_end))

    downloaded_frames: list[pd.DataFrame] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, PRICE_DOWNLOAD_WORKERS)) as executor:
        futures = {
            executor.submit(_download_or_load_cache, ticker, ticker_start, ticker_end): ticker
            for ticker, ticker_start, ticker_end in download_jobs
        }
        for future in as_completed(futures):
            ticker = futures[future]
            completed += 1
            try:
                ticker, prices, from_cache, cache_path = future.result()
                if prices.empty:
                    stats["tickers_missing"] += 1
                    stats["errors"].append(f"No data for {ticker}")
                    logger.warning(
                        "[%d/%d] No price data found for %s; continuing",
                        completed,
                        len(tickers),
                        ticker,
                    )
                    continue

                downloaded_frames.append(prices)
                if from_cache:
                    stats["tickers_cached"] += 1
                else:
                    stats["tickers_downloaded"] += 1
                logger.info(
                    "[%d/%d] %s %s: %d rows, first day %s, last day %s (%s)",
                    completed,
                    len(tickers),
                    "Loaded cached" if from_cache else "Downloaded",
                    ticker,
                    len(prices),
                    prices["price_date"].min(),
                    prices["price_date"].max(),
                    cache_path,
                )
            except Exception as e:
                stats["errors"].append(f"{ticker}: {e}")
                logger.exception(
                    "[%d/%d] Error preparing %s; continuing with other tickers",
                    completed,
                    len(tickers),
                    ticker,
                )

    if downloaded_frames:
        all_prices = pd.concat(downloaded_frames, ignore_index=True)
        all_prices = all_prices.drop_duplicates(subset=["ticker", "price_date"], keep="last")
        all_prices = all_prices.sort_values(["ticker", "price_date"])
        total_rows = len(all_prices)
        total_batches = (total_rows + PRICE_UPLOAD_BATCH_SIZE - 1) // PRICE_UPLOAD_BATCH_SIZE
        logger.info(
            "Download/cache phase complete: %d ticker files and %d price rows ready. "
            "Uploading to Azure in %d batches...",
            len(downloaded_frames),
            total_rows,
            total_batches,
        )
        try:
            with get_connection() as conn:
                for batch_number, offset in enumerate(
                    range(0, total_rows, PRICE_UPLOAD_BATCH_SIZE), start=1
                ):
                    batch = all_prices.iloc[offset : offset + PRICE_UPLOAD_BATCH_SIZE]
                    count = upsert_daily_prices(conn, batch)
                    stats["rows_upserted"] += count
                    logger.info(
                        "Uploaded Azure batch %d/%d: %d rows (%d/%d total rows)",
                        batch_number,
                        total_batches,
                        count,
                        stats["rows_upserted"],
                        total_rows,
                    )
            stats["tickers_processed"] = len(downloaded_frames)
        except Exception as e:
            stats["errors"].append(f"Azure price upload: {e}")
            logger.exception(
                "Azure upload failed after %d rows. Cached CSV files were retained; "
                "rerun the command to resume",
                stats["rows_upserted"],
            )
    else:
        logger.warning("No price rows are available to upload")

    try:
        with get_connection() as conn:
            log_sync_finish(
                conn,
                log_id,
                "success" if not stats["errors"] else "failed",
                message=str(stats["errors"][:5]) if stats["errors"] else "OK",
                records_affected=stats["rows_upserted"],
            )
    except Exception:
        logger.exception(
            "Could not update the Azure sync log; cached price files remain available"
        )

    logger.info(
        "Price sync finished: %d/%d tickers uploaded (%d newly downloaded, %d cached), "
        "%d returned no data, %d rows upserted, %d total errors",
        stats["tickers_processed"],
        stats["tickers_total"],
        stats["tickers_downloaded"],
        stats["tickers_cached"],
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
