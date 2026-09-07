import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type StrategyTrade } from "../api/client";

export default function RecentStrategyTrades({ fundId, strategy }: { fundId: number; strategy: "top10" | "new_to_exit" }) {
  const [trades, setTrades] = useState<StrategyTrade[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    api.strategyTrades(fundId, strategy).then(data => { if (active) setTrades(data.trades); })
      .catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [fundId, strategy]);
  return <div className="recent-trades"><h3>Latest 5 Trades</h3>
    <p className="chart-note">Most recent entries in the selected strategy. Entry levels use the backtest’s adjusted-price basis. P&amp;L compounds simulated period returns, before costs; open trades are valued through the date shown.</p>
    {error ? <div className="error" role="alert">Unable to load trades: {error}</div>
      : !trades ? <div role="status">Loading recent trades...</div>
      : trades.length === 0 ? <p>No simulated trades available.</p>
      : <div className="table-scroll"><table><thead><tr><th>Position</th><th>Entry date</th>
        <th className="text-right">Entry level</th><th>Status</th><th>Exit / valuation date</th><th className="text-right">P&amp;L %</th>
      </tr></thead><tbody>{trades.map((trade, index) => <tr key={`${trade.ticker}:${trade.entry_date}:${index}`}>
        <td><Link className="ticker-link" to={`/securities/${encodeURIComponent(trade.ticker)}`}>{trade.ticker}</Link></td>
        <td>{trade.entry_date ?? "—"}</td>
        <td className="text-right">{trade.entry_price == null ? "—" : `$${Number(trade.entry_price).toFixed(2)}`}</td>
        <td>{trade.is_closed ? "Closed" : "Open"}{!trade.resolved && " · Incomplete prices"}</td>
        <td>{trade.as_of_date ?? "—"}</td>
        <td className={`text-right ${trade.pnl == null ? "" : trade.pnl >= 0 ? "positive" : "negative"}`}>
          {trade.pnl == null ? "—" : `${trade.pnl >= 0 ? "+" : ""}${(trade.pnl * 100).toFixed(2)}%`}</td>
      </tr>)}</tbody></table></div>}
  </div>;
}
