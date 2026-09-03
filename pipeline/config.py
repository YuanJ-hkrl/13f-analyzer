"""Shared configuration for data pipeline."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
FUNDS_JSON = BASE_DIR / "data" / "funds.json"

# Load .env from project root (works when running from pipeline/)
load_dotenv(BASE_DIR / ".env")

# Azure SQL connection string
# Format: mssql+pyodbc://user:password@server.database.windows.net/dbname?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no
DATABASE_URL = os.getenv("DATABASE_URL", "")

# SEC EDGAR requires a User-Agent with contact email
SEC_IDENTITY = os.getenv("SEC_IDENTITY", "13f-analyzer@example.com")

# How many quarters of 13F history to fetch per fund on initial sync
DEFAULT_QUARTERS_BACK = int(os.getenv("DEFAULT_QUARTERS_BACK", "8"))

# Benchmark ticker for backtest comparison
BENCHMARK_TICKER = os.getenv("BENCHMARK_TICKER", "SPY")

# Price sync tuning
PRICE_DOWNLOAD_WORKERS = int(os.getenv("PRICE_DOWNLOAD_WORKERS", "6"))
PRICE_UPLOAD_BATCH_SIZE = int(os.getenv("PRICE_UPLOAD_BATCH_SIZE", "5000"))
PRICE_CACHE_DIR = Path(os.getenv("PRICE_CACHE_DIR", str(BASE_DIR / "data" / "price_cache")))
DB_CONNECT_RETRIES = int(os.getenv("DB_CONNECT_RETRIES", "4"))

# How unresolved backtest positions contribute to portfolio return:
# "zero_cash" treats them as a zero-return allocation; "renormalize" excludes them.
BACKTEST_UNRESOLVED_POLICY = os.getenv("BACKTEST_UNRESOLVED_POLICY", "zero_cash").lower()
if BACKTEST_UNRESOLVED_POLICY not in {"zero_cash", "renormalize"}:
    raise ValueError("BACKTEST_UNRESOLVED_POLICY must be 'zero_cash' or 'renormalize'")

TRADE_COPY_COST_BPS = float(os.getenv("TRADE_COPY_COST_BPS", "10"))
TRADE_COPY_WEIGHT_CHANGE_THRESHOLD = float(
    os.getenv("TRADE_COPY_WEIGHT_CHANGE_THRESHOLD", "0.0025")
)
TRADE_COPY_UNRESOLVED_POLICY = os.getenv(
    "TRADE_COPY_UNRESOLVED_POLICY", "zero_cash"
).lower()
if TRADE_COPY_UNRESOLVED_POLICY not in {"zero_cash", "renormalize"}:
    raise ValueError("TRADE_COPY_UNRESOLVED_POLICY must be 'zero_cash' or 'renormalize'")
