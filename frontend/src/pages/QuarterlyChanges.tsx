import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type QuarterlyChange, type QuarterlyChangeType } from "../api/client";

const sections: { key: QuarterlyChangeType; label: string }[] = [
  { key: "new", label: "New Positions" },
  { key: "add", label: "Added Positions" },
  { key: "reduce", label: "Reduced Positions" },
  { key: "exit", label: "Exited Positions" },
];

const pct = (value: number | string) => `${(Number(value) * 100).toFixed(2)}%`;

function ChangeTable({ rows, rankBy }: { rows: QuarterlyChange[]; rankBy: string }) {
  return (
    <table>
      <thead><tr><th>#</th><th>Ticker</th><th className="text-right">Funds</th>
        <th className="text-right">Group exposure change</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.ticker}>
            <td>{row.rank_number}</td><td><Link className="ticker-link" to={`/securities/${row.ticker}`}><strong>{row.ticker}</strong></Link></td>
            <td className={`text-right ${rankBy === "fund_count" ? "positive" : ""}`}>{row.fund_count}</td>
            <td className={`text-right ${Number(row.group_percentage_change) >= 0 ? "positive" : "negative"}`}>
              {pct(row.group_percentage_change)}
            </td>
          </tr>
        ))}
        {!rows.length && <tr><td colSpan={4}>No comparable changes found.</td></tr>}
      </tbody>
    </table>
  );
}

export default function QuarterlyChanges() {
  const [quarters, setQuarters] = useState<string[]>([]);
  const [quarter, setQuarter] = useState("");
  const [fundType, setFundType] = useState("All");
  const [rankBy, setRankBy] = useState("fund_count");
  const [changes, setChanges] = useState<Record<QuarterlyChangeType, QuarterlyChange[]>>({ new: [], add: [], reduce: [], exit: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.quarterlyChangeQuarters()
      .then((data) => { setQuarters(data.quarters); if (data.quarters.length) setQuarter(data.quarters[0]); })
      .catch((err) => { setError(err.message); setLoading(false); });
  }, []);

  useEffect(() => {
    if (!quarter) return;
    setLoading(true); setError(null);
    api.quarterlyChanges(quarter, fundType, rankBy)
      .then((data) => setChanges(data.changes))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [quarter, fundType, rankBy]);

  return (
    <>
      <div className="page-header"><h1>Quarterly Significant Changes</h1>
        <p>Aggregated 13F position changes versus each fund’s preceding reported quarter.</p></div>
      <div className="filter-bar">
        <select className="period-select" value={quarter} onChange={(e) => setQuarter(e.target.value)}>
          {quarters.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select className="period-select" value={fundType} onChange={(e) => setFundType(e.target.value)}>
          <option>All</option><option>Long Only</option><option>Hedge Core</option>
        </select>
        <select className="period-select" value={rankBy} onChange={(e) => setRankBy(e.target.value)}>
          <option value="fund_count">Number of funds</option>
          <option value="group_percentage">Aggregate group percentage</option>
        </select>
      </div>
      {error && <div className="error">{error}</div>}
      {loading ? <div className="loading">Calculating changes...</div> :
        <div className="change-grid">{sections.map((section) =>
          <div className="card" key={section.key}><h2>{section.label}</h2>
            <ChangeTable rows={changes[section.key]} rankBy={rankBy} /></div>)}</div>}
    </>
  );
}
