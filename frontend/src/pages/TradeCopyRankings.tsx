import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type TradeCopyRanking } from "../api/client";

type SortKey =
  | "annualized_return"
  | "average_alpha"
  | "trade_hit_rate"
  | "excess_hit_rate"
  | "top10_hit_rate"
  | "average_price_coverage";

const numberValue = (value: number | string | null | undefined) =>
  value == null ? Number.NEGATIVE_INFINITY : Number(value);

const percent = (value: number | string | null | undefined) =>
  value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;

export default function TradeCopyRankings() {
  const [rankings, setRankings] = useState<TradeCopyRanking[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("annualized_return");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.tradeCopyRankings()
      .then((data) => setRankings(data.rankings))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const sorted = useMemo(
    () => [...rankings].sort((a, b) => numberValue(b[sortKey]) - numberValue(a[sortKey])),
    [rankings, sortKey]
  );

  if (loading) return <div className="loading">Loading trade-copy rankings...</div>;

  return (
    <>
      <div className="page-header">
        <h1>Trade-Copy Rankings</h1>
        <p>Investable returns begin at the first market close after each 13F filing date.</p>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="filter-bar">
        <label>
          Rank by{" "}
          <select
            className="period-select"
            value={sortKey}
            onChange={(event) => setSortKey(event.target.value as SortKey)}
          >
            <option value="annualized_return">Annualized return</option>
            <option value="average_alpha">Average alpha</option>
            <option value="trade_hit_rate">Trade hit rate</option>
            <option value="excess_hit_rate">Excess hit rate</option>
            <option value="top10_hit_rate">Top-10 hit rate</option>
            <option value="average_price_coverage">Price coverage</option>
          </select>
        </label>
      </div>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>#</th><th>Fund</th><th className="text-right">Ann. return</th>
              <th className="text-right">Avg. alpha</th><th className="text-right">Trade hit</th>
              <th className="text-right">Excess hit</th><th className="text-right">Top-10 hit</th>
              <th className="text-right">Coverage</th><th className="text-right">Periods</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((fund, index) => (
              <tr key={fund.fund_id} onClick={() => navigate(`/trade-copy/funds/${fund.fund_id}`)} style={{ cursor: "pointer" }}>
                <td>{index + 1}</td><td>{fund.name}</td>
                <td className="text-right">{percent(fund.annualized_return)}</td>
                <td className="text-right">{percent(fund.average_alpha)}</td>
                <td className="text-right">{percent(fund.trade_hit_rate)} ({fund.resolved_trades ?? 0})</td>
                <td className="text-right">{percent(fund.excess_hit_rate)}</td>
                <td className="text-right">{percent(fund.top10_hit_rate)} ({fund.resolved_top10 ?? 0})</td>
                <td className="text-right">{percent(fund.average_price_coverage)}</td>
                <td className="text-right">{fund.periods}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
