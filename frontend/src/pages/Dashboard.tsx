import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type ConsensusChange, type DashboardData, type DashboardFund } from "../api/client";

const numeric = (value: number | string | null | undefined) => value == null ? null : Number(value);
const percent = (value: number | string | null | undefined) => {
  const number = numeric(value);
  return number == null ? "—" : `${number >= 0 ? "+" : ""}${(number * 100).toFixed(1)}%`;
};
const money = (dollars: number | string | null | undefined) => {
  const value = numeric(dollars);
  if (value == null) return "—";
  const sign = value < 0 ? "−" : "";
  if (Math.abs(value) >= 1_000_000_000) return `${sign}$${(Math.abs(value) / 1_000_000_000).toFixed(1)}B`;
  if (Math.abs(value) >= 1_000_000) return `${sign}$${(Math.abs(value) / 1_000_000).toFixed(1)}M`;
  return `${sign}$${Math.round(Math.abs(value)).toLocaleString("en-US")}`;
};
const netMoney = (dollars: number | string | null | undefined) => {
  const value = numeric(dollars);
  if (value == null) return "—";
  return `${value < 0 ? "−" : ""}$${Math.round(Math.abs(value)).toLocaleString("en-US")}`;
};

function ConsensusTable({ title, rows, side }: { title: string; rows: ConsensusChange[]; side: "buy" | "sell" }) {
  const maxFunds = Math.max(...rows.map((row) => row.fund_count), 1);
  return <section className={`consensus-panel consensus-${side}`}><h2>{title}</h2><table>
    <thead><tr><th>Ticker</th><th>Company</th><th>Funds</th>
      <th className="text-right">Move since Qtr End</th><th className="text-right">Net Δ</th></tr></thead>
    <tbody>{rows.map((row) => {
      const move = numeric(row.move_since_quarter_end);
      return <tr key={row.ticker}>
        <td><span className="row-rank">{String(row.rank_number).padStart(2, "0")}</span> <Link className="ticker-link" to={`/securities/${row.ticker}`}><strong>{row.ticker}</strong></Link></td>
        <td className="company-cell">{row.company}</td>
        <td><span className="fund-bar"><span style={{ width: `${Math.max(12, row.fund_count / maxFunds * 72)}px` }} /></span>{row.fund_count}</td>
        <td className={`text-right ${move != null && move >= 0 ? "positive" : "negative"}`}>{percent(move)}</td>
        <td className={`text-right ${side === "buy" ? "positive" : "negative"}`}>{side === "buy" ? "▲ " : "▼ "}{netMoney(row.net_change)}</td>
      </tr>;
    })}</tbody>
  </table></section>;
}

type FundSort = keyof Pick<DashboardFund, "name" | "aum" | "holdings" | "latest_quarter" | "filing_date" | "annualized_return" | "annualized_alpha">;

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<FundSort>("annualized_return");
  const [ascending, setAscending] = useState(false);
  const navigate = useNavigate();

  useEffect(() => { api.dashboard().then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false)); }, []);
  const funds = useMemo(() => [...(data?.funds ?? [])].sort((a, b) => {
    const av = a[sortKey]; const bv = b[sortKey];
    if (av == null) return 1; if (bv == null) return -1;
    const comparison = sortKey === "name" || sortKey.includes("date") || sortKey === "latest_quarter"
      ? String(av).localeCompare(String(bv)) : Number(av) - Number(bv);
    return ascending ? comparison : -comparison;
  }), [data, sortKey, ascending]);
  const sort = (key: FundSort) => {
    if (key === sortKey) setAscending(!ascending); else { setSortKey(key); setAscending(key === "name"); }
  };
  const sortArrow = (key: FundSort) => key === sortKey ? (ascending ? " ▲" : " ▼") : " △";

  if (loading) return <div className="loading">Loading dashboard...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!data) return null;

  return <><div className="page-header"><h1>Fund Intelligence Dashboard</h1>
    <p>Quarter-end 13F proxy performance and the latest consensus positioning changes.</p></div>
    <div className="quarter-return-grid">{data.recent_quarters.map((quarter, index) => {
      const result = numeric(quarter.aggregate_return) ?? 0;
      const isReportingQuarter = index === 0;
      const displayEnd = isReportingQuarter
        ? (quarter.period_end ?? "last price date")
        : (data.recent_quarters[index - 1]?.period_start ?? quarter.period_end ?? "next quarter end");
      return <div className={`quarter-return-card ${isReportingQuarter ? "reporting-card" : ""}`} key={quarter.period_start}>
        <div className="quarter-label">{quarter.period_start} to {displayEnd}</div>
        {isReportingQuarter ? <><div className={result >= 0 ? "quarter-value positive" : "quarter-value negative"}>{percent(result)} <small>QTD</small></div>
          <div className="quarter-comparison"><span>SPY {percent(quarter.benchmark_return)}</span><span>Alpha {percent(quarter.aggregate_alpha)}</span></div>
          <div className="quarter-funds">{quarter.reporting_count}/{quarter.total_funds} funds reported · through {quarter.period_end ?? "latest price"}</div></> : <>
          <div className={result >= 0 ? "quarter-value positive" : "quarter-value negative"}>{percent(result)}</div>
          <div className="quarter-comparison"><span>SPY {percent(quarter.benchmark_return)}</span><span>Alpha {percent(quarter.aggregate_alpha)}</span></div>
          <div className="quarter-funds">Equal-weighted · {quarter.fund_count} funds</div></>}
      </div>;
    })}</div>
    <div className="consensus-grid">
      <ConsensusTable title={`Consensus Buys · ${data.latest_quarter ?? "Latest"}`} rows={data.consensus.buys} side="buy" />
      <ConsensusTable title={`Consensus Sells · ${data.latest_quarter ?? "Latest"}`} rows={data.consensus.sells} side="sell" />
    </div>
    <section className="card dashboard-funds"><h2>Tracked Funds</h2><div className="table-scroll"><table>
      <thead><tr><th onClick={() => sort("name")}>Fund{sortArrow("name")}</th><th onClick={() => sort("aum")} className="text-right">13F AUM{sortArrow("aum")}</th>
        <th onClick={() => sort("holdings")} className="text-right">Holdings{sortArrow("holdings")}</th><th onClick={() => sort("latest_quarter")}>Latest Quarter{sortArrow("latest_quarter")}</th>
        <th onClick={() => sort("filing_date")}>File Date{sortArrow("filing_date")}</th><th onClick={() => sort("annualized_return")} className="text-right">Ann. Return{sortArrow("annualized_return")}</th>
        <th onClick={() => sort("annualized_alpha")} className="text-right">Ann. Alpha (SPY){sortArrow("annualized_alpha")}</th></tr></thead>
      <tbody>{funds.map((fund) => <tr key={fund.fund_id} onClick={() => navigate(`/funds/${fund.fund_id}`)}>
        <td><strong>{fund.name}</strong> <span className={`badge ${fund.fund_type === "Long Only" ? "badge-long" : "badge-hedge"}`}>{fund.fund_type}</span></td><td className="text-right">{money(fund.aum)}</td>
        <td className="text-right">{fund.holdings ?? "—"}</td><td>{fund.latest_quarter ?? "—"}</td><td>{fund.filing_date ?? "—"}</td>
        <td className={`text-right ${(numeric(fund.annualized_return) ?? 0) >= 0 ? "positive" : "negative"}`}>{percent(fund.annualized_return)}</td>
        <td className={`text-right ${(numeric(fund.annualized_alpha) ?? 0) >= 0 ? "positive" : "negative"}`}>{percent(fund.annualized_alpha)}</td>
      </tr>)}</tbody>
    </table></div></section>
  </>;
}
