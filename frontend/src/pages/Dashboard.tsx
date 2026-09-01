import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DashboardSummary } from "../api/client";

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .dashboard()
      .then((data) => setSummary(data.summary))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">Loading dashboard...</div>;
  if (error) return <div className="error">{error}</div>;

  return (
    <>
      <div className="page-header">
        <h1>Dashboard</h1>
        <p>13F institutional holdings analysis for your tracked fund universe</p>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Tracked Funds</div>
          <div className="value">{summary?.total_funds ?? 0}</div>
        </div>
        <div className="stat-card">
          <div className="label">13F Filings</div>
          <div className="value">{summary?.total_filings ?? 0}</div>
        </div>
        <div className="stat-card">
          <div className="label">Unique Tickers</div>
          <div className="value">{summary?.unique_tickers ?? 0}</div>
        </div>
        <div className="stat-card">
          <div className="label">Backtest Periods</div>
          <div className="value">{summary?.backtest_periods ?? 0}</div>
        </div>
      </div>

      <div className="card">
        <h2>Getting Started</h2>
        <p style={{ color: "var(--text-secondary)", marginBottom: "1rem" }}>
          Run the data pipeline to populate holdings from EDGAR and prices from yfinance,
          then explore fund portfolios and quarterly backtest results.
        </p>
        <Link to="/funds">Browse Funds &rarr;</Link>
      </div>
    </>
  );
}
