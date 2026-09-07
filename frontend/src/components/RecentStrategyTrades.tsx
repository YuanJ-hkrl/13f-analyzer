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
    <p className="chart-note">Latest buy/sell events, newest first. Trade dates are the first market close after the filing. P&amp;L is the position’s return since entry, before costs: realized when closed, or marked to the latest stored stock price when open. Prices use the adjusted-close basis; quotes are not live.</p>
    {error ? <div className="error" role="alert">Unable to load trades: {error}</div>
      : !trades ? <div role="status">Loading recent trades...</div>
      : trades.length === 0 ? <p>No simulated trades available.</p>
      : <div className="table-scroll"><table><thead><tr><th>Position ticker</th><th>Trade</th>
        <th>Trade Date</th><th className="text-right">P&amp;L</th><th>Entry Date</th>
      </tr></thead><tbody>{trades.map((trade, index) => <tr key={`${trade.ticker}:${trade.trade}:${trade.trade_date}:${index}`}>
        <td><Link className="ticker-link" to={`/securities/${encodeURIComponent(trade.ticker)}`}>{trade.ticker}</Link></td>
        <td><span className={`change-pill ${trade.trade === "buy" ? "change-added" : "change-exit"}`}>{trade.trade === "buy" ? "Buy" : "Sell"}</span></td>
        <td>{trade.trade_date}</td>
        <td className={`text-right ${trade.pnl == null ? "" : trade.pnl >= 0 ? "positive" : "negative"}`}>
          {trade.pnl == null ? "Unavailable" : `${trade.pnl >= 0 ? "+" : ""}${(trade.pnl * 100).toFixed(2)}%`}
          <div className="trade-valuation">{trade.pnl_type === "realized" ? "Realized · Closed" : "Mark-to-market · Open"}
            {trade.as_of_date && ` · ${trade.as_of_date}`}</div></td>
        <td>{trade.entry_date}</td>
      </tr>)}</tbody></table></div>}
  </div>;
}
