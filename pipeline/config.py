"""Shared configuration for data pipeline."""

import os
from pathlib import Path

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
