import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  BarChart,
  Bar,
} from "recharts";
import { api, type Fund, type Holding, type BacktestResult } from "../api/client";

function formatValue(thousands: number): string {
  const millions = thousands / 1000;
  if (millions >= 1000) return `$${(millions / 1000).toFixed(1)}B`;
  if (millions >= 1) return `$${millions.toFixed(1)}M`;
  return `$${thousands}K`;
}

export default function FundDetail() {
  const { id } = useParams<{ id: string }>();
  const fundId = Number(id);

  const [fund, setFund] = useState<(Fund & { latest_total_value?: number }) | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [periods, setPeriods] = useState<string[]>([]);
  const [selectedPeriod, setSelectedPeriod] = useState<string>("");
  const [backtest, setBacktest] = useState<BacktestResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!fundId) return;
    setLoading(true);
    Promise.all([api.fund(fundId), api.holdings(fundId), api.backtest(fundId)])
      .then(([fundData, holdingsData, backtestData]) => {
        setFund(fundData);
        setHoldings(holdingsData.holdings);
        setPeriods(holdingsData.available_periods);
        if (holdingsData.available_periods.length > 0) {
          setSelectedPeriod(holdingsData.available_periods[0]);
        }
        setBacktest(backtestData.backtest);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [fundId]);

  useEffect(() => {
    if (!fundId || !selectedPeriod) return;
    api
      .holdings(fundId, selectedPeriod)
      .then((data) => setHoldings(data.holdings))
      .catch((e) => setError(e.message));
  }, [fundId, selectedPeriod]);

  if (loading) return <div className="loading">Loading fund details...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!fund) return <div className="error">Fund not found</div>;

  const chartData = backtest.map((b) => ({
    period: b.period_start.slice(0, 7),
    return: +(b.total_return * 100).toFixed(2),
    benchmark: b.benchmark_return != null ? +(b.benchmark_return * 100).toFixed(2) : null,
    alpha: b.alpha != null ? +(b.alpha * 100).toFixed(2) : null,
  }));

  const topHoldings = holdings.slice(0, 10);

  return (
    <>
      <Link to="/funds" className="back-link">
        &larr; Back to Funds
      </Link>

      <div className="page-header">
        <h1>{fund.name}</h1>
        <p>
          <span
            className={`badge ${fund.fund_type === "Long Only" ? "badge-long" : "badge-hedge"}`}
          >
            {fund.fund_type}
          </span>
          {" · "}
          CIK {fund.cik}
          {fund.latest_total_value != null && ` · AUM ${formatValue(fund.latest_total_value)}`}
        </p>
      </div>

      {backtest.length > 0 && (
        <div className="card">
          <h2>Quarterly Performance Backtest</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem", marginBottom: "1rem" }}>
            Value-weighted portfolio return vs SPY benchmark, based on disclosed 13F holdings
          </p>
          <div className="chart-container">
            <ResponsiveContainer>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2e3344" />
                <XAxis dataKey="period" stroke="#9aa0b0" fontSize={12} />
                <YAxis stroke="#9aa0b0" fontSize={12} tickFormatter={(v) => `${v}%`} />
                <Tooltip
                  contentStyle={{ background: "#222633", border: "1px solid #2e3344" }}
                  formatter={(value) => [`${value ?? 0}%`, ""]}
                />
                <Legend />
                <Bar dataKey="return" name="Portfolio" fill="#4f8cff" />
                <Bar dataKey="benchmark" name="SPY" fill="#6366f1" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {chartData.some((d) => d.alpha != null) && (
            <div className="chart-container" style={{ marginTop: "1.5rem" }}>
              <ResponsiveContainer>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2e3344" />
                  <XAxis dataKey="period" stroke="#9aa0b0" fontSize={12} />
                  <YAxis stroke="#9aa0b0" fontSize={12} tickFormatter={(v) => `${v}%`} />
                  <Tooltip
                    contentStyle={{ background: "#222633", border: "1px solid #2e3344" }}
                    formatter={(value) => [`${value ?? 0}%`, "Alpha"]}
                  />
                  <Line type="monotone" dataKey="alpha" stroke="#34d399" strokeWidth={2} dot />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <h2 style={{ margin: 0 }}>Holdings</h2>
          {periods.length > 0 && (
            <select
              className="period-select"
              value={selectedPeriod}
              onChange={(e) => setSelectedPeriod(e.target.value)}
            >
              {periods.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          )}
        </div>

        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Ticker</th>
              <th>Issuer</th>
              <th className="text-right">Shares</th>
              <th className="text-right">Value</th>
              <th className="text-right">Weight</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h, i) => (
              <tr key={`${h.ticker}-${i}`}>
                <td>{i + 1}</td>
                <td>
                  <strong>{h.ticker || "—"}</strong>
                  {h.put_call && (
                    <span style={{ color: "var(--text-secondary)", fontSize: "0.75rem" }}>
                      {" "}
                      ({h.put_call})
                    </span>
                  )}
                </td>
                <td>{h.issuer_name}</td>
                <td className="text-right">{h.shares.toLocaleString()}</td>
                <td className="text-right">{formatValue(h.value_usd)}</td>
                <td className="text-right">{h.weight_pct != null ? `${h.weight_pct}%` : "—"}</td>
              </tr>
            ))}
            {holdings.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", color: "var(--text-secondary)" }}>
                  No holdings data. Run the EDGAR sync pipeline first.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {topHoldings.length > 0 && (
        <div className="card">
          <h2>Top 10 Positions</h2>
          <div className="chart-container">
            <ResponsiveContainer>
              <BarChart data={topHoldings} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#2e3344" />
                <XAxis type="number" stroke="#9aa0b0" fontSize={12} tickFormatter={(v) => `${v}%`} />
                <YAxis type="category" dataKey="ticker" stroke="#9aa0b0" fontSize={12} width={60} />
                <Tooltip
                  contentStyle={{ background: "#222633", border: "1px solid #2e3344" }}
                  formatter={(value) => [`${value ?? 0}%`, "Weight"]}
                />
                <Bar dataKey="weight_pct" fill="#4f8cff" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </>
  );
}
