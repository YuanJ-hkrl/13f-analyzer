import { Fragment, useEffect, useMemo, useState } from "react";
import { api, type StrategyBacktestFund } from "../api/client";
import RecentStrategyTrades from "../components/RecentStrategyTrades";

type Strategy = "top10" | "new_to_exit";
type SortKey = "annualized_return" | "cumulative_return" | "win_rate" | "average_trade_return";
const percent = (value:number|string|null|undefined) => value == null ? "—" : `${Number(value)>=0?"+":""}${(Number(value)*100).toFixed(1)}%`;
const numeric = (value:number|string|null|undefined) => value == null ? -Infinity : Number(value);
const descriptions:Record<Strategy,string> = {
  top10:"Buy when a security enters a fund’s disclosed top 10 and sell when it leaves the top 10. Positions are equal-weighted.",
  new_to_exit:"Buy after a security first appears in a fund’s filing and hold it until the fund reports a full exit. Active positions are equal-weighted.",
};

export default function StrategyBacktests() {
  const [strategy,setStrategy] = useState<Strategy>("top10");
  const [rows,setRows] = useState<StrategyBacktestFund[]>([]);
  const [sortKey,setSortKey] = useState<SortKey>("annualized_return");
  const [loading,setLoading] = useState(true);
  const [error,setError] = useState<string|null>(null);
  const [expandedFund,setExpandedFund] = useState<number|null>(null);
  useEffect(()=>{ let active=true; setLoading(true); setError(null); api.strategyBacktests(strategy)
    .then((data)=>{if(active)setRows(data.funds);}).catch((err)=>{if(active)setError(err.message);})
    .finally(()=>{if(active)setLoading(false);}); return ()=>{active=false;}; },[strategy]);
  const sorted=useMemo(()=>[...rows].sort((a,b)=>numeric(b[sortKey])-numeric(a[sortKey])),[rows,sortKey]);

  return <><div className="page-header"><h1>Strategy Backtests</h1><p>Compare rules-based 13F copy strategies using the first market close after filing publication.</p></div>
    <div className="filter-bar"><label>Strategy{" "}<select className="period-select" value={strategy} onChange={(e)=>{setExpandedFund(null);setStrategy(e.target.value as Strategy);}}>
      <option value="top10">Top 10 trades</option><option value="new_to_exit">New trades to exit</option></select></label>
      <label>Rank by{" "}<select className="period-select" value={sortKey} onChange={(e)=>setSortKey(e.target.value as SortKey)}>
        <option value="annualized_return">Annualized return</option><option value="cumulative_return">Cumulative return</option>
        <option value="win_rate">Trade win rate</option><option value="average_trade_return">Average trade return</option></select></label></div>
    <p className="chart-note">{descriptions[strategy]} Each active resolved trade receives 1/N weight in every period; weights reset as holdings change. Returns are gross of transaction costs; unresolved price periods are excluded.</p>
    {error && <div className="error">{error}</div>}
    {loading ? <div className="loading">Loading strategy results...</div> : <div className="card table-scroll"><table><thead><tr>
      <th>#</th><th>Fund</th><th>Group</th><th className="text-right">Ann. return</th><th className="text-right">Cumulative</th>
      <th className="text-right">Winning trades</th><th className="text-right">Win rate</th><th className="text-right">Avg. trade</th>
      <th className="text-right">Coverage</th><th className="text-right">Periods</th></tr></thead>
      <tbody>{sorted.map((row,index)=><Fragment key={row.fund_id}><tr><td>{index+1}</td><td><button type="button" className="fund-expand-button" aria-expanded={expandedFund===row.fund_id} aria-controls={`fund-trades-${row.fund_id}`} onClick={()=>setExpandedFund(expandedFund===row.fund_id?null:row.fund_id)}>
        <span aria-hidden="true">{expandedFund===row.fund_id?"▾":"▸"}</span> <strong>{row.name}</strong></button></td>
        <td><span className={`badge ${row.fund_type==="Long Only"?"badge-long":"badge-hedge"}`}>{row.fund_type}</span></td>
        <td className={`text-right ${numeric(row.annualized_return)>=0?"positive":"negative"}`}>{percent(row.annualized_return)}</td>
        <td className={`text-right ${numeric(row.cumulative_return)>=0?"positive":"negative"}`}>{percent(row.cumulative_return)}</td>
        <td className="text-right">{row.winning_trades}/{row.resolved_trades}</td><td className="text-right">{percent(row.win_rate)}</td>
        <td className="text-right">{percent(row.average_trade_return)}</td><td className="text-right">{percent(row.price_coverage)}</td>
        <td className="text-right">{row.periods}</td></tr>
        {expandedFund===row.fund_id && <tr id={`fund-trades-${row.fund_id}`}><td colSpan={10}>
          <RecentStrategyTrades key={`${strategy}:${row.fund_id}`} fundId={row.fund_id} strategy={strategy}/>
        </td></tr>}</Fragment>)}</tbody></table></div>}</>;
}
