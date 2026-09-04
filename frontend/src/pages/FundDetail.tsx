import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, Treemap, XAxis, YAxis,
} from "recharts";
import { api, type BacktestResult, type Fund, type Holding, type TradeCopyResult } from "../api/client";

const numeric = (value: number | string | null | undefined) => value == null ? null : Number(value);
const percent = (value: number | string | null | undefined) => {
  const parsed = numeric(value);
  return parsed == null ? "—" : `${parsed >= 0 ? "+" : ""}${(parsed * 100).toFixed(1)}%`;
};
const money = (value: number) => {
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  return `$${Math.round(value).toLocaleString("en-US")}`;
};
const shareCount = (value: number) => {
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000) return `${(absolute / 1_000_000).toFixed(2)}M`;
  if (absolute >= 1_000) return `${(absolute / 1_000).toFixed(1)}K`;
  return absolute.toLocaleString("en-US");
};
const holdingPeriod = (value: number | string | null | undefined) => {
  const quarters = numeric(value);
  return quarters == null ? "—" : `${quarters.toFixed(1)} quarters`;
};

const changeColors: Record<Holding["change_type"], string> = {
  new: "#080a0e", added: "#10b981", reduced: "#ef4444", exit: "#ef4444", unchanged: "#64748b",
};

function TreemapCell(props: { x?: number; y?: number; width?: number; height?: number; name?: string; change_type?: Holding["change_type"] }) {
  const { x = 0, y = 0, width = 0, height = 0, name = "", change_type = "unchanged" } = props;
  return <g><rect x={x} y={y} width={width} height={height} fill={changeColors[change_type]} stroke="#111827" strokeWidth={2}/>
    {width > 48 && height > 28 && <text x={x + 7} y={y + 18} fill="#fff" fontSize={12} fontWeight={700}>{name}</text>}
  </g>;
}

function cumulativeSeries(rows: { date: string; value: number | null }[]) {
  let growth = 1;
  return rows.map((row) => {
    if (row.value != null) growth *= 1 + row.value;
    return { date: row.date, value: (growth - 1) * 100 };
  });
}

export default function FundDetail() {
  const { id } = useParams<{ id: string }>();
  const fundId = Number(id);
  const [fund, setFund] = useState<Fund | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [latestHoldings, setLatestHoldings] = useState<Holding[]>([]);
  const [periods, setPeriods] = useState<string[]>([]);
  const [selectedPeriod, setSelectedPeriod] = useState("");
  const [backtest, setBacktest] = useState<BacktestResult[]>([]);
  const [tradeCopy, setTradeCopy] = useState<TradeCopyResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!fundId) return;
    Promise.all([api.fund(fundId), api.holdings(fundId), api.backtest(fundId), api.fundTradeCopy(fundId)])
      .then(([fundData, holdingsData, backtestData, tradeCopyData]) => {
        setFund(fundData);
        setHoldings(holdingsData.holdings);
        setLatestHoldings(holdingsData.holdings);
        setPeriods(holdingsData.available_periods);
        setSelectedPeriod(holdingsData.available_periods[0] ?? "");
        setBacktest(backtestData.backtest);
        setTradeCopy(tradeCopyData.trade_copy);
      }).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [fundId]);

  useEffect(() => {
    if (!fundId || !selectedPeriod) return;
    if (selectedPeriod === periods[0]) {
      setHoldings(latestHoldings);
      return;
    }
    api.holdings(fundId, selectedPeriod).then((data) => setHoldings(data.holdings)).catch((e) => setError(e.message));
  }, [fundId, selectedPeriod, periods, latestHoldings]);

  const performanceData = useMemo(() => {
    const quarter = cumulativeSeries(backtest.map((row) => ({ date: row.period_end, value: numeric(row.total_return) })));
    const spy = cumulativeSeries(backtest.map((row) => ({ date: row.period_end, value: numeric(row.benchmark_return) })));
    const copy = cumulativeSeries(tradeCopy.map((row) => ({ date: row.exit_date, value: numeric(row.total_return) })));
    const merged = new Map<string, { date: string; quarterEnd?: number; tradeCopy?: number; spy?: number }>();
    quarter.forEach((row) => merged.set(row.date, { ...(merged.get(row.date) ?? { date: row.date }), quarterEnd: row.value }));
    spy.forEach((row) => merged.set(row.date, { ...(merged.get(row.date) ?? { date: row.date }), spy: row.value }));
    copy.forEach((row) => merged.set(row.date, { ...(merged.get(row.date) ?? { date: row.date }), tradeCopy: row.value }));
    return [...merged.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [backtest, tradeCopy]);

  const alphaData = backtest.map((row) => ({ period: row.period_start.slice(0, 7), alpha: (numeric(row.alpha) ?? 0) * 100 }));
  const treeData = latestHoldings.filter((row) => row.value_usd > 0 && row.change_type !== "exit").map((row) => ({
    name: row.ticker || row.issuer_name, size: row.value_usd, weight: numeric(row.weight_pct) ?? 0,
    change_type: row.change_type,
  }));

  if (loading) return <div className="loading">Loading fund details...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!fund) return <div className="error">Fund not found</div>;

  return <>
    <Link to="/funds" className="back-link">&larr; Back to Funds</Link>
    <div className="page-header"><h1>{fund.name}</h1><p>
      <span className={`badge ${fund.fund_type === "Long Only" ? "badge-long" : "badge-hedge"}`}>{fund.fund_type}</span>
      {` · CIK ${fund.cik}`}{fund.latest_total_value != null && ` · 13F AUM ${money(Number(fund.latest_total_value))}`}
    </p></div>

    <div className="fund-detail-metrics">
      <div className="quarter-return-card"><div className="quarter-label">Return since {fund.latest_period ?? "last report"}</div><div className={`quarter-value ${(numeric(fund.return_since_report) ?? 0) >= 0 ? "positive" : "negative"}`}>{percent(fund.return_since_report)}</div></div>
      <div className="quarter-return-card"><div className="quarter-label">Average historical holding period</div><div className="quarter-value">{holdingPeriod(fund.average_holding_period_quarters)}</div></div>
    </div>

    <section className="card"><h2>Cumulative Performance</h2>
      <p className="chart-note">Growth of $1, compounded independently. Quarter-end uses disclosed holdings; trade-copy begins after filing publication.</p>
      <div className="chart-container"><ResponsiveContainer><LineChart data={performanceData}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2e3344"/><XAxis dataKey="date" stroke="#9aa0b0" fontSize={11}/>
        <YAxis stroke="#9aa0b0" fontSize={12} tickFormatter={(v) => `${v}%`}/>
        <Tooltip contentStyle={{ background: "#222633", border: "1px solid #2e3344" }} formatter={(v) => [`${Number(v).toFixed(1)}%`, ""]}/><Legend/>
        <Line connectNulls type="monotone" dataKey="quarterEnd" name="Quarter-end performance" stroke="#4f8cff" strokeWidth={2} dot={false}/>
        <Line connectNulls type="monotone" dataKey="tradeCopy" name="Trade-copy performance" stroke="#34d399" strokeWidth={2} dot={false}/>
        <Line connectNulls type="monotone" dataKey="spy" name="SPY" stroke="#a78bfa" strokeWidth={2} dot={false}/>
      </LineChart></ResponsiveContainer></div>
    </section>

    <section className="card"><h2>Quarterly Alpha vs SPY</h2>
      <div className="chart-container"><ResponsiveContainer><BarChart data={alphaData}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2e3344"/><XAxis dataKey="period" stroke="#9aa0b0" fontSize={11}/>
        <YAxis stroke="#9aa0b0" fontSize={12} tickFormatter={(v) => `${v}%`}/>
        <Tooltip contentStyle={{ background: "#222633", border: "1px solid #2e3344" }} formatter={(v) => [`${Number(v).toFixed(1)}%`, "Alpha"]}/>
        <Bar dataKey="alpha" name="Alpha">{alphaData.map((row, index) => <Cell key={index} fill={row.alpha >= 0 ? "#34d399" : "#ef4444"}/>)}</Bar>
      </BarChart></ResponsiveContainer></div>
    </section>

    {treeData.length > 0 && <section className="card"><h2>Latest 13F Portfolio Changes</h2>
      <p className="chart-note">All positions present in the latest filing; area represents disclosed market value.</p>
      <div className="treemap-legend"><span className="legend-new">New</span><span className="legend-added">Added</span><span className="legend-reduced">Reduced</span><span className="legend-unchanged">Unchanged</span></div>
      <div className="portfolio-treemap"><ResponsiveContainer><Treemap data={treeData} dataKey="size" nameKey="name" content={<TreemapCell/>}>
        <Tooltip contentStyle={{ background: "#222633", border: "1px solid #2e3344" }} formatter={(v, _name, item) => [money(Number(v)), `${item.payload.name} · ${item.payload.change_type}`]}/>
      </Treemap></ResponsiveContainer></div>
    </section>}

    <section className="card holdings-card"><div className="holdings-heading"><div><h2>Holdings</h2><p className="chart-note">Position changes versus the immediately preceding 13F filing.</p></div>
      {periods.length > 0 && <select className="period-select" value={selectedPeriod} onChange={(e) => setSelectedPeriod(e.target.value)}>
        {periods.map((period) => <option key={period} value={period}>{period}</option>)}
      </select>}
    </div><div className="table-scroll"><table className="holdings-detail-table"><thead><tr>
      <th>Ticker</th><th>Company</th><th>Change</th><th className="text-right">Value</th><th className="text-right">% Port</th>
      <th className="text-right">Shares</th><th className="text-right">Δ Shares (QoQ)</th><th className="text-right">Since Filed</th>
    </tr></thead><tbody>{holdings.map((holding, index) => {
      const delta = numeric(holding.share_change) ?? 0;
      const deltaPct = numeric(holding.share_change_pct);
      const sinceFiled = numeric(holding.since_filed_return);
      return <tr key={`${holding.ticker}-${holding.cusip}-${index}`}>
        <td><span className="row-rank">{String(index + 1).padStart(2, "0")}</span> {holding.ticker ? <Link className="ticker-link" to={`/securities/${holding.ticker}`}><strong>{holding.ticker}</strong></Link> : "—"}</td>
        <td className="holding-company">{holding.issuer_name}</td><td><span className={`change-pill change-${holding.change_type}`}>{holding.change_type}</span></td>
        <td className="text-right">{money(holding.value_usd)}</td><td className="text-right">{holding.change_type === "exit" ? "—" : `${Number(holding.weight_pct).toFixed(1)}%`}</td>
        <td className="text-right">{shareCount(holding.shares)}</td>
        <td className={`text-right ${delta > 0 ? "positive" : delta < 0 ? "negative" : ""}`}>{holding.change_type === "new" ? "new" : delta === 0 ? "—" : `${delta > 0 ? "▲" : "▼"} ${shareCount(delta)}${deltaPct == null ? "" : ` (${deltaPct >= 0 ? "+" : ""}${(deltaPct * 100).toFixed(0)}%)`}`}</td>
        <td className={`text-right ${sinceFiled == null ? "" : sinceFiled >= 0 ? "positive" : "negative"}`}>{percent(sinceFiled)}</td>
      </tr>;
    })}</tbody></table></div></section>
  </>;
}
