export interface Fund {
  id: number;
  name: string;
  fund_type: string;
  cik: string;
  filing_count: number;
  latest_period: string | null;
}

export interface Holding {
  ticker: string;
  cusip: string;
  issuer_name: string;
  shares: number;
  value_usd: number;
  put_call: string | null;
  report_period: string;
  filing_date: string;
  weight_pct: number;
}

export interface BacktestResult {
  period_start: string;
  period_end: string;
  total_return: number;
  benchmark_return: number | null;
  alpha: number | null;
  num_positions: number;
}

export interface DashboardSummary {
  total_funds: number;
  total_filings: number;
  unique_tickers: number;
  backtest_periods: number;
}

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

async function fetchApi<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || `API error ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => fetchApi<{ status: string }>("/health"),
  dashboard: () => fetchApi<{ summary: DashboardSummary; recent_sync: unknown[] }>("/dashboard"),
  funds: (type?: string) =>
    fetchApi<{ funds: Fund[] }>(type ? `/funds?type=${encodeURIComponent(type)}` : "/funds"),
  fund: (id: number) => fetchApi<Fund & { latest_total_value: number }>(`/funds/${id}`),
  holdings: (id: number, period?: string) =>
    fetchApi<{ holdings: Holding[]; available_periods: string[] }>(
      period ? `/funds/${id}/holdings?period=${period}` : `/funds/${id}/holdings`
    ),
  backtest: (id: number) => fetchApi<{ backtest: BacktestResult[] }>(`/funds/${id}/backtest`),
  filings: (id: number) => fetchApi<{ filings: unknown[] }>(`/funds/${id}/filings`),
};
