import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AlphaAttribution as Position } from "../api/client";

function PositionTable({ title, rows }: { title: string; rows: Position[] }) {
  return <div className="attribution-panel"><h3>{title}</h3><div className="table-scroll"><table>
    <thead><tr><th>Position</th><th className="text-right">Annualized alpha contribution</th></tr></thead>
    <tbody>{rows.map(row => <tr key={row.ticker}>
      <td><Link className="ticker-link" to={`/securities/${encodeURIComponent(row.ticker)}`}>{row.ticker}</Link></td>
      <td className={`text-right ${row.annualized_alpha > 0 ? "positive" : "negative"}`}>
        {row.annualized_alpha > 0 ? "+" : ""}{(row.annualized_alpha * 100).toFixed(2)}%
      </td>
    </tr>)}{rows.length === 0 && <tr><td colSpan={2}>No qualifying positions.</td></tr>}</tbody>
  </table></div></div>;
}

export default function AlphaAttribution({ fundId }: { fundId: number }) {
  const [result, setResult] = useState<{ fundId: number; contributors: Position[]; detractors: Position[] } | null>(null);
  const [failure, setFailure] = useState<{ fundId: number; message: string } | null>(null);
  useEffect(() => {
    let active = true;
    api.fundAlpha(fundId).then(data => { if (active) setResult({ fundId, ...data }); })
      .catch(error => { if (active) setFailure({ fundId, message: error.message }); });
    return () => { active = false; };
  }, [fundId]);
  const data = result?.fundId === fundId ? result : null;
  const error = failure?.fundId === fundId ? failure.message : null;
  const period = data?.contributors[0] ?? data?.detractors[0];
  return <section className="card"><h2>Alpha Contribution / Detraction</h2>
    <p className="chart-note">Trade-copy attribution vs SPY: sum of position weight × excess return, divided by simulated history in years. Arithmetic annualization, not position CAGR. Resolved periods only; figures are percentage points of portfolio alpha per year.
      {period && ` History: ${period.history_start} to ${period.history_end}.`}</p>
    {error ? <div className="error" role="alert">Alpha attribution unavailable: {error}</div>
      : !data ? <div className="loading" role="status">Loading alpha attribution...</div>
      : <div className="attribution-grid"><PositionTable title="Top 5 Alpha Contributors" rows={data.contributors}/>
        <PositionTable title="Top 5 Alpha Detractors" rows={data.detractors}/></div>}
  </section>;
}
