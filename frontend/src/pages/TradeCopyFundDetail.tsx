import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  api, type Fund, type TickerPricePoint, type TickerSignal,
  type TradeCopyAttribution, type TradeCopyResult,
} from "../api/client";

const num = (value: number | string | null | undefined) => value == null ? null : Number(value);
const pct = (value: number | string | null | undefined, alreadyPercent = false) => {
  const parsed = num(value);
  if (parsed == null) return "—";
  const result = alreadyPercent ? parsed : parsed * 100;
  return `${result >= 0 ? "+" : ""}${result.toFixed(1)}%`;
};

function cumulative(rows: TradeCopyResult[]) {
  let strategy = 1;
  let spy = 1;
  return rows.map((row) => {
    strategy *= 1 + Number(row.total_return);
    if (row.benchmark_return != null) spy *= 1 + Number(row.benchmark_return);
    return {
      date: row.exit_date,
      strategy: (strategy - 1) * 100,
      spy: (spy - 1) * 100,
      alpha: Number(row.alpha ?? 0) * 100,
    };
  });
}

function AttributionTable({ title, rows }: { title: string; rows: TradeCopyAttribution[] }) {
  return <section className="attribution-panel"><h3>{title}</h3><table><thead><tr>
    <th>Ticker</th><th className="text-right">Return contribution</th><th className="text-right">Alpha contribution</th><th className="text-right">Periods</th>
  </tr></thead><tbody>{rows.map((row, index) => <tr key={row.ticker}>
    <td><span className="row-rank">{String(index + 1).padStart(2, "0")}</span> <Link className="ticker-link" to={`/securities/${row.ticker}`}><strong>{row.ticker}</strong></Link></td>
    <td className={`text-right ${Number(row.contribution) >= 0 ? "positive" : "negative"}`}>{pct(row.contribution)}</td>
    <td className={`text-right ${Number(row.excess_contribution) >= 0 ? "positive" : "negative"}`}>{pct(row.excess_contribution)}</td>
    <td className="text-right">{row.periods}</td>
  </tr>)}</tbody></table></section>;
}

export default function TradeCopyFundDetail() {
  const fundId = Number(useParams<{ id: string }>().id);
  const [fund, setFund] = useState<Fund | null>(null);
  const [periods, setPeriods] = useState<TradeCopyResult[]>([]);
  const [contributors, setContributors] = useState<TradeCopyAttribution[]>([]);
  const [detractors, setDetractors] = useState<TradeCopyAttribution[]>([]);
  const [tickers, setTickers] = useState<string[]>([]);
  const [ticker, setTicker] = useState("");
  const [prices, setPrices] = useState<TickerPricePoint[]>([]);
  const [signals, setSignals] = useState<TickerSignal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [panelError, setPanelError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!fundId) return;
    Promise.all([api.fund(fundId), api.fundTradeCopy(fundId)])
      .then(([fundData, periodData]) => {
        setFund(fundData);
        setPeriods(periodData.trade_copy);
      }).catch((e) => setError(e.message)).finally(() => setLoading(false));
    api.tradeCopyAttribution(fundId).then((attribution) => {
        setContributors(attribution.contributors);
        setDetractors(attribution.detractors);
        setTickers(attribution.tickers);
        setTicker(attribution.contributors[0]?.ticker ?? attribution.tickers[0] ?? "");
      }).catch((e) => setPanelError(`Attribution unavailable: ${e.message}`));
  }, [fundId]);

  useEffect(() => {
    if (!ticker) return;
    api.tradeCopyTickerPrices(fundId, ticker).then((data) => {
      setPrices(data.prices);
      setSignals(data.signals);
    }).catch((e) => setPanelError(`Price history unavailable: ${e.message}`));
  }, [fundId, ticker]);

  const chartData = useMemo(() => cumulative(periods), [periods]);
  const priceData = useMemo(() => {
    const points = new Map<string, { date: string; price?: number; shares?: number; action?: TickerSignal["action"] }>();
    prices.forEach((row) => points.set(row.price_date, { date: row.price_date, price: Number(row.price) }));
    signals.forEach((signal) => {
      points.set(signal.report_period, {
        ...(points.get(signal.report_period) ?? { date: signal.report_period }),
        shares: Number(signal.position_shares),
        action: signal.action,
      });
    });
    return [...points.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [prices, signals]);

  if (loading) return <div className="loading">Loading trade-copy analysis...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!fund) return <div className="error">Fund not found</div>;

  return <>
    <Link to="/trade-copy" className="back-link">&larr; Back to Trade-Copy Rankings</Link>
    <div className="page-header"><h1>{fund.name}</h1><p>Trade-copy performance and position-level attribution.</p></div>
    {panelError && <div className="error">{panelError}</div>}

    <section className="card"><h2>Cumulative Trade-Copy Performance</h2><div className="chart-container"><ResponsiveContainer><LineChart data={chartData}>
      <CartesianGrid strokeDasharray="3 3" stroke="#2e3344"/><XAxis dataKey="date" stroke="#9aa0b0" fontSize={11}/><YAxis stroke="#9aa0b0" tickFormatter={(v) => `${v}%`}/>
      <Tooltip contentStyle={{ background: "#222633", border: "1px solid #2e3344" }} formatter={(v) => [`${Number(v).toFixed(1)}%`, ""]}/><Legend/>
      <Line type="monotone" dataKey="strategy" name="Trade-copy" stroke="#10b981" strokeWidth={2} dot={false}/>
      <Line type="monotone" dataKey="spy" name="SPY" stroke="#a78bfa" strokeWidth={2} dot={false}/>
    </LineChart></ResponsiveContainer></div></section>

    <section className="card"><h2>Quarterly Trade-Copy Alpha vs SPY</h2><div className="chart-container"><ResponsiveContainer><BarChart data={chartData}>
      <CartesianGrid strokeDasharray="3 3" stroke="#2e3344"/><XAxis dataKey="date" stroke="#9aa0b0" fontSize={11}/><YAxis stroke="#9aa0b0" tickFormatter={(v) => `${v}%`}/>
      <Tooltip contentStyle={{ background: "#222633", border: "1px solid #2e3344" }} formatter={(v) => [`${Number(v).toFixed(1)}%`, "Alpha"]}/>
      <Bar dataKey="alpha">{chartData.map((row, index) => <Cell key={index} fill={row.alpha >= 0 ? "#10b981" : "#ef4444"}/>)}</Bar>
    </BarChart></ResponsiveContainer></div></section>

    <section className="card"><h2>Return Attribution</h2><p className="chart-note">Position weights × subsequent returns, summed across all simulated periods.</p>
      <div className="attribution-grid"><AttributionTable title="Top 10 Contributors" rows={contributors}/><AttributionTable title="Top 10 Detractors" rows={detractors}/></div>
    </section>

    <section className="card"><div className="ticker-chart-heading"><div><h2>Ticker Price and Disclosed Position</h2><p className="chart-note">The filled area is the shares reported for each quarter. A quarter without this holding is shown as zero.</p></div>
      <select className="period-select" value={ticker} onChange={(event) => setTicker(event.target.value)}>{tickers.map((item) => <option key={item}>{item}</option>)}</select>
    </div>
      <div className="price-chart"><ResponsiveContainer><ComposedChart data={priceData}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2e3344"/><XAxis dataKey="date" stroke="#9aa0b0" fontSize={11}/>
        <YAxis yAxisId="price" stroke="#4f8cff" domain={["auto", "auto"]} tickFormatter={(v) => `$${v}`}/>
        <YAxis yAxisId="shares" orientation="right" stroke="#10b981" tickFormatter={(v) => Number(v).toLocaleString("en-US", { notation: "compact" })}/>
        <Tooltip contentStyle={{ background: "#222633", border: "1px solid #2e3344" }} formatter={(value, name) => name === "Reported shares" ? [Number(value).toLocaleString("en-US"), name] : [`$${Number(value).toFixed(2)}`, name]}/>
        <Legend/><Area connectNulls yAxisId="shares" type="stepAfter" dataKey="shares" name="Reported shares" stroke="#10b981" fill="#10b981" fillOpacity={0.28}/>
        <Line connectNulls yAxisId="price" type="monotone" dataKey="price" name={`${ticker} price`} stroke="#4f8cff" strokeWidth={2} dot={false}/>
      </ComposedChart></ResponsiveContainer></div>
    </section>
  </>;
}
