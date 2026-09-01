import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Fund } from "../api/client";

type Filter = "all" | "Long Only" | "Hedge Core";

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
            <h3>{fund.name}</h3>
            <span
              className={`badge ${fund.fund_type === "Long Only" ? "badge-long" : "badge-hedge"}`}
            >
              {fund.fund_type}
            </span>
            <div className="meta" style={{ marginTop: "0.75rem" }}>
              {fund.filing_count} filings
              {fund.latest_period && ` · Latest: ${fund.latest_period}`}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
