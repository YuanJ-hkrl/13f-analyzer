import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Fund } from "../api/client";

type Filter = "all" | "Long Only" | "Hedge Core";
const percent = (value: number | string | null) => value == null ? "—" : `${Number(value) >= 0 ? "+" : ""}${(Number(value) * 100).toFixed(1)}%`;
const holdingPeriod = (value: number | string | null) => {
  if (value == null) return "—";
  return `${Number(value).toFixed(1)} qtrs`;
};

export default function FundList() {
  const [funds, setFunds] = useState<Fund[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    const type = filter === "all" ? undefined : filter;
    api
      .funds(type)
      .then((data) => setFunds(data.funds))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [filter]);

  if (loading) return <div className="loading">Loading funds...</div>;

  return (
    <>
      <div className="page-header">
        <h1>Fund Universe</h1>
        <p>{funds.length} institutional managers tracked</p>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="filter-bar">
        {(["all", "Long Only", "Hedge Core"] as Filter[]).map((f) => (
          <button
            key={f}
            className={`filter-btn ${filter === f ? "active" : ""}`}
            onClick={() => setFilter(f)}
          >
            {f === "all" ? "All Funds" : f}
          </button>
        ))}
      </div>

      <div className="fund-grid">
        {funds.map((fund) => (
          <div
            key={fund.id}
            className="fund-card"
            onClick={() => navigate(`/funds/${fund.id}`)}
          >
            <div className="fund-card-main">
              <div className="fund-card-metrics">
                <div><span>Return since {fund.latest_period ?? "last report"}</span><strong className={fund.return_since_report == null ? "" : Number(fund.return_since_report) >= 0 ? "positive" : "negative"}>{percent(fund.return_since_report)}</strong></div>
                <div><span>Avg historical hold</span><strong>{holdingPeriod(fund.average_holding_period_quarters)}</strong></div>
              </div>
              <h3>{fund.name}</h3>
              <div className="fund-card-meta">
                <span className={`badge ${fund.fund_type === "Long Only" ? "badge-long" : "badge-hedge"}`}>{fund.fund_type}</span>
                <span>{fund.filing_count} filings</span>
                <span>{fund.latest_period ? `Latest: ${fund.latest_period}` : "No filings"}</span>
              </div>
            </div>
            <div className="fund-top-positions"><span>Top 5 positions</span><ol>{fund.top_positions.map((position) => <li key={`${position.ticker}-${position.issuer_name}`}><b>{position.ticker || "—"}</b><small>{position.issuer_name}</small></li>)}</ol></div>
          </div>
        ))}
      </div>
    </>
  );
}
