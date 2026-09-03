# 13F Analyzer

A 13F institutional holdings analysis tool (similar to [alpha-tracer.com](https://alpha-tracer.com)), built for a curated fund universe. Holdings are sourced from SEC EDGAR, stock prices from yfinance (MVP), with data stored in Azure SQL Database and the web app hosted on Azure Static Web Apps.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  SEC EDGAR      │────▶│  Python Pipeline │────▶│  Azure SQL DB   │
│  (13F filings)  │     │  (sync_all.py)   │     │                 │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
┌─────────────────┐                                       │
│  yfinance       │────▶ price_data.py ──────────────────▶│
│  (stock prices) │                                       │
└─────────────────┘                                       ▼
                                                 ┌─────────────────┐
                                                 │ Azure Functions │
                                                 │ (REST API)      │
                                                 └────────┬────────┘
                                                          │
                                                 ┌────────▼────────┐
                                                 │ Azure Static    │
                                                 │ Web App (React) │
                                                 └─────────────────┘
```

## Project Structure

| Path | Description |
|------|-------------|
| `database/schema.sql` | Azure SQL table definitions |
| `data/funds.json` | Your curated fund list (32 funds) |
| `pipeline/` | Data ingestion: EDGAR 13F, yfinance prices, backtest |
| `api/` | Azure Functions REST API |
| `frontend/` | React + TypeScript dashboard |
| `staticwebapp.config.json` | Azure SWA routing config |

## Quick Start

### 1. Azure SQL Database

Run the schema against your Azure SQL instance:

```bash
# Using sqlcmd or Azure Data Studio
sqlcmd -S your-server.database.windows.net -d 13f-analyzer -U admin -P 'password' -i database/schema.sql
```

### 2. Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | SQLAlchemy connection string for Azure SQL |
| `SEC_IDENTITY` | Your email (required by SEC fair access policy) |
| `BENCHMARK_TICKER` | Benchmark for backtest (default: `SPY`) |

**Connection string format:**

```
mssql+pyodbc://USER:PASSWORD@SERVER.database.windows.net/DATABASE?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no
```

### 3. Data Pipeline

```bash
cd pipeline
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Full sync: EDGAR → prices → backtest
python sync_all.py

# Or run individual steps
python sync_all.py --step edgar --quarters 8
python sync_all.py --step prices
python sync_all.py --step backtest
```

The price step downloads tickers concurrently, caches each completed ticker under
`data/price_cache/`, and then uploads cached rows to Azure SQL in batches. Re-running
the step with the same date range reuses completed cache files. Tune concurrency and
batch size with `PRICE_DOWNLOAD_WORKERS` and `PRICE_UPLOAD_BATCH_SIZE` in `.env`.

The pipeline:
1. **EDGAR 13F** — Downloads quarterly 13F-HR filings for each fund in `data/funds.json`
2. **Price Data** — Fetches OHLCV history via yfinance for all tickers in holdings
3. **Backtest** — Computes quarterly value-weighted portfolio returns vs SPY

### 4. Local Development

**API (Azure Functions):**

```bash
cd api
pip install -r requirements.txt
# Set DATABASE_URL in local.settings.json
func start
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — API calls proxy to `localhost:7071`.

### 5. Deploy to Azure Static Web Apps

1. Create an Azure Static Web App in the Azure Portal (or via CLI)
2. Link to this GitHub repository
3. Configure build settings:
   - **App location:** `frontend/dist` (built by CI)
   - **API location:** `api`
4. Add `DATABASE_URL` to SWA Application Settings
5. Add `AZURE_STATIC_WEB_APPS_API_TOKEN` to GitHub Secrets

## Fund Universe

32 institutional managers across two categories:

- **Long Only** (18 funds): TCI, Viking Global, Fundsmith, Lone Pine, etc.
- **Hedge Core** (14 funds): Coatue, Tiger Global, Whale Rock, D1 Capital, etc.

Fund list is defined in `data/funds.json`. CIK numbers are pre-populated but should be verified — run `python cik_lookup.py` to refresh from EDGAR search.

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Health check |
| `GET /api/dashboard` | Summary statistics |
| `GET /api/funds` | List all funds (`?type=Long+Only`) |
| `GET /api/funds/{id}` | Fund details |
| `GET /api/funds/{id}/holdings` | Holdings (`?period=2024-09-30`) |
| `GET /api/funds/{id}/backtest` | Quarterly backtest results |
| `GET /api/funds/{id}/filings` | Filing history |

## Backtest Methodology (MVP)

For each quarter's disclosed 13F holdings:

1. Take positions at quarter-end (`report_period`)
2. Compute value-weighted return to next quarter (~92 days)
3. Compare against SPY benchmark
4. Report alpha = portfolio return − benchmark return

`backtest_results` is a quarter-end 13F return proxy for comparison with external
fund-return data; it is not an investable strategy. The separate trade-copy model
enters at the first market close after a filing becomes public and exits/rebalances
after the next filing. Run `database/add_trade_copy_analysis.sql`, then execute
`python sync_all.py --step trade-copy`. Set `TRADE_COPY_UNRESOLVED_POLICY=zero_cash`
(default) to assign unresolved copy positions a 0% return, or `renormalize` to
exclude their weights from the trade-copy return.

Limitations (MVP):
- Uses disclosed holdings only (45-day filing lag)
- Does not account for intra-quarter trading
- Options (PUT/CALL) excluded from equity backtest
- yfinance prices may have gaps for delisted tickers

## Scheduled Sync

For production, run the pipeline on a schedule (e.g., Azure Container Apps Job, GitHub Actions cron, or Azure Logic Apps) after each 13F filing season (mid-Feb, mid-May, mid-Aug, mid-Nov):

```yaml
# Example GitHub Actions cron (add to workflow)
schedule:
  - cron: '0 6 16 2,5,8,11 *'  # 16th of filing months
```

## Next Steps

- [ ] Verify CIK mappings for all 32 funds
- [ ] Add CUSIP → ticker mapping for holdings missing tickers
- [ ] Quarter-over-quarter holdings diff (new buys / sells)
- [ ] Upgrade price data source (Polygon, Alpha Vantage)
- [ ] Azure Key Vault for connection strings
- [ ] Authentication for internal company use
