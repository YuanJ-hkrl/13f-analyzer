#!/usr/bin/env python3
"""Run full data sync pipeline: seed funds -> EDGAR 13F -> prices -> backtest."""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    parser = argparse.ArgumentParser(description="13F Analyzer data sync pipeline")
    parser.add_argument(
        "--step",
        choices=["all", "edgar", "prices", "backtest", "trade-copy", "summaries"],
        default="all",
        help="Which pipeline step to run",
    )
    parser.add_argument(
        "--quarters",
        type=int,
        default=8,
        help="Number of quarters of 13F history to fetch",
    )
    args = parser.parse_args()

    edgar_result = None

    if args.step in ("all", "edgar"):
        from edgar_13f import sync_all_funds

        logging.info("=== Syncing 13F filings from EDGAR ===")
        edgar_result = sync_all_funds(max_filings=args.quarters)
        logging.info("EDGAR sync result: %s", edgar_result)
        if edgar_result.get("errors") or edgar_result.get("funds_with_zero_filings"):
            logging.warning("EDGAR step completed with warnings/errors.")
        else:
            logging.info("EDGAR step completed successfully.")

    if args.step in ("all", "edgar", "summaries"):
        from summaries import refresh_position_summaries

        logging.info("=== Refreshing persisted position summaries ===")
        result = refresh_position_summaries()
        logging.info("Summary refresh result: %s", result)

    if args.step in ("all", "prices"):
        from price_data import sync_prices

        logging.info("=== Syncing stock prices via yfinance ===")
        result = sync_prices()
        logging.info("Price sync result: %s", result)

    if args.step in ("all", "backtest"):
        from backtest import run_all_backtests

        logging.info("=== Running portfolio backtests ===")
        result = run_all_backtests()
        logging.info("Backtest result: %s", result)

    if args.step in ("all", "trade-copy"):
        from trade_copy import run_all_trade_copy

        logging.info("=== Running investable trade-copy simulations ===")
        result = run_all_trade_copy()
        logging.info("Trade-copy result: %s", result)

    if args.step == "all":
        if edgar_result and (edgar_result.get("errors") or edgar_result.get("funds_with_zero_filings")):
            logging.warning("Pipeline completed with warnings/errors.")
        else:
            logging.info("Pipeline complete.")
    else:
        logging.info("Pipeline step complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
