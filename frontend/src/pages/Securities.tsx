import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type SecuritySearchResult } from "../api/client";

const money=(v:number|string)=>{const n=Number(v);return n>=1e9?`$${(n/1e9).toFixed(1)}B`:n>=1e6?`$${(n/1e6).toFixed(1)}M`:`$${n.toLocaleString()}`};
export default function Securities(){
 const [q,setQ]=useState(""); const [rows,setRows]=useState<SecuritySearchResult[]>([]); const [loading,setLoading]=useState(true); const [error,setError]=useState(""); const nav=useNavigate();
 useEffect(()=>{const timer=setTimeout(()=>{setLoading(true);api.securities(q).then(d=>setRows(d.securities)).catch(e=>setError(e.message)).finally(()=>setLoading(false));},250);return()=>clearTimeout(timer)},[q]);
 return <><div className="page-header"><h1>Securities</h1><p>Search the complete tracked 13F security universe.</p></div>
 <input className="security-search" value={q} onChange={e=>setQ(e.target.value)} placeholder="Search ticker or company name…" autoFocus/>
 {error&&<div className="error">{error}</div>}{loading?<div className="loading">Searching securities...</div>:<div className="card"><table><thead><tr><th>Ticker</th><th>Company</th><th className="text-right">Latest price</th><th className="text-right">Tracked owners</th><th className="text-right">Aggregate 13F value</th></tr></thead>
 <tbody>{rows.map(r=><tr className="clickable-row" key={r.ticker} onClick={()=>nav(`/securities/${r.ticker}`)}><td><strong>{r.ticker}</strong></td><td>{r.company}</td><td className="text-right">{r.latest_price==null?"—":`$${Number(r.latest_price).toFixed(2)}`}</td><td className="text-right">{r.owner_count}</td><td className="text-right">{money(r.aggregate_value)}</td></tr>)}</tbody></table></div>}</>;
}
