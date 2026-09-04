export interface Fund {
  id: number;
  name: string;
  fund_type: string;
  cik: string;
  filing_count: number;
  latest_period: string | null;
  latest_filing_date: string | null;
  latest_total_value: number | string | null;
  return_since_report: number | string | null;
  average_holding_period_quarters: number | string | null;
  top_positions: FundTopPosition[];
}

export interface FundTopPosition {
  fund_id: number;
  ticker: string | null;
  issuer_name: string;
  position_value: number | string;
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
  previous_shares: number;
  share_change: number;
  share_change_pct: number | null;
  change_type: "new" | "added" | "reduced" | "exit" | "unchanged";
  since_filed_return: number | null;
}

export interface BacktestResult {
  period_start: string;
  period_end: string;
  total_return: number;
  benchmark_return: number | null;
  alpha: number | null;
  num_positions: number;
}

export interface DashboardQuarter {
  period_start: string;
  period_end: string;
  aggregate_return: number | string;
  benchmark_return: number | string | null;
  aggregate_alpha: number | string | null;
  fund_count: number;
  reporting_count: number;
  total_funds: number;
}

export interface TradeCopyResult {
  entry_date: string;
  exit_date: string;
  total_return: number;
  benchmark_return: number | null;
  alpha: number | null;
}

export interface TradeCopyAttribution {
  ticker: string;
  contribution: number | string;
  excess_contribution: number | string;
  periods: number;
  average_return: number | string;
}

export interface TickerPricePoint { price_date: string; price: number | string; }
export interface TickerSignal {
  filing_date: string;
  marker_date: string;
  report_period: string;
  position_value: number;
  previous_value: number | null;
  position_shares: number | string;
  previous_shares: number | string | null;
  action: "new" | "add" | "reduce" | "exit" | null;
}

export interface SecuritySearchResult { ticker:string; company:string; owner_count:number; aggregate_value:number|string; latest_price:number|string|null; price_date:string|null; }
export interface SecurityHistory { report_period:string; fund_count:number; aggregate_value:number|string; aggregate_shares:number|string; quarter_price:number|string|null; }
export interface SecurityFundPosition { fund_id:number; name:string; fund_type:string; report_period:string; value_usd:number|string; shares:number|string; portfolio_weight:number|string; first_owned:string; }
export interface SecurityActivity { fund_id:number; name:string; fund_type:string; shares:number|string; previous_shares:number|string; value_usd:number|string; previous_value:number|string; action:"new"|"add"|"reduce"|"exit"; }
export type SecurityPositionAction = "new" | "add" | "reduce" | "exit" | "unchanged";
export interface SecurityPositionChange { fund_id:number; name:string; fund_type:string; report_period:string; shares:number|string; previous_shares:number|string; action:SecurityPositionAction; }
export interface SecurityDetailData {
  security:{ticker:string;company:string;first_appearance:string;latest_price:number|string|null;price_date:string|null};
  history:SecurityHistory[]; owners:SecurityFundPosition[]; buyers:SecurityActivity[]; sellers:SecurityActivity[];
  position_changes:{quarters:string[];rows:SecurityPositionChange[]}; prices:TickerPricePoint[];
}

export interface ConsensusChange {
  side: "buy" | "sell";
  ticker: string;
  company: string;
  fund_count: number;
  move_since_quarter_end: number | string | null;
  net_change: number | string;
  rank_number: number;
}

export interface DashboardFund {
  fund_id: number;
  name: string;
  fund_type: string;
  aum: number | string | null;
  holdings: number | null;
  latest_quarter: string | null;
  filing_date: string | null;
  backtest_periods: number | null;
  annualized_return: number | string | null;
  annualized_alpha: number | string | null;
}

export interface DashboardData {
  recent_quarters: DashboardQuarter[];
  latest_quarter: string | null;
  consensus: { buys: ConsensusChange[]; sells: ConsensusChange[] };
  funds: DashboardFund[];
}

export interface TradeCopyRanking {
  fund_id: number;
  name: string;
  fund_type: string;
  periods: number;
  annualized_return: number | string | null;
  cumulative_return: number | string;
  average_alpha: number | string | null;
  average_price_coverage: number | string;
  average_turnover: number | string;
  resolved_trades: number;
  trade_hit_rate: number | string | null;
  excess_hit_rate: number | string | null;
  resolved_top10: number;
  top10_hit_rate: number | string | null;
}

export interface StrategyBacktestFund {
  fund_id:number; name:string; fund_type:string; periods:number;
  cumulative_return:number|string; annualized_return:number|string|null;
  trade_count:number; resolved_trades:number; winning_trades:number;
  win_rate:number|string|null; average_trade_return:number|string|null;
  price_coverage:number|string; first_entry:string; last_exit:string;
}

export type QuarterlyChangeType = "new" | "add" | "reduce" | "exit";

export interface QuarterlyChange {
  change_type: QuarterlyChangeType;
  ticker: string;
  fund_count: number;
  current_value: number | string;
  previous_value: number | string;
  current_group_percentage: number | string;
  previous_group_percentage: number | string;
  group_percentage_change: number | string;
  rank_number: number;
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
  securities: (query = "") => fetchApi<{ securities: SecuritySearchResult[] }>(`/securities?q=${encodeURIComponent(query)}`),
  security: (ticker: string) => fetchApi<SecurityDetailData>(`/securities/${encodeURIComponent(ticker)}`),
  dashboard: () => fetchApi<DashboardData>("/dashboard"),
  funds: (type?: string) =>
    fetchApi<{ funds: Fund[] }>(type ? `/funds?type=${encodeURIComponent(type)}` : "/funds"),
  fund: (id: number) => fetchApi<Fund>(`/funds/${id}`),
  holdings: (id: number, period?: string) =>
    fetchApi<{ holdings: Holding[]; available_periods: string[] }>(
      period ? `/funds/${id}/holdings?period=${period}` : `/funds/${id}/holdings`
    ),
  backtest: (id: number) => fetchApi<{ backtest: BacktestResult[] }>(`/funds/${id}/backtest`),
  fundTradeCopy: (id: number) =>
    fetchApi<{ trade_copy: TradeCopyResult[] }>(`/funds/${id}/trade-copy`),
  tradeCopyAttribution: (id: number) => fetchApi<{
    contributors: TradeCopyAttribution[]; detractors: TradeCopyAttribution[]; tickers: string[];
  }>(`/funds/${id}/trade-copy/attribution`),
  tradeCopyTickerPrices: (id: number, ticker: string) => fetchApi<{
    ticker: string; prices: TickerPricePoint[]; signals: TickerSignal[];
  }>(`/funds/${id}/trade-copy/prices?ticker=${encodeURIComponent(ticker)}`),
  filings: (id: number) => fetchApi<{ filings: unknown[] }>(`/funds/${id}/filings`),
  tradeCopyRankings: () =>
    fetchApi<{ rankings: TradeCopyRanking[] }>("/trade-copy/rankings"),
  strategyBacktests: (strategy: "top10" | "new_to_exit") =>
    fetchApi<{ strategy:string; funds:StrategyBacktestFund[] }>(`/strategy-backtests?strategy=${strategy}`),
  quarterlyChangeQuarters: () =>
    fetchApi<{ quarters: string[] }>("/quarterly-changes/quarters"),
  quarterlyChanges: (quarter: string, fundType: string, rankBy: string) => {
    const params = new URLSearchParams({ quarter, rank_by: rankBy });
    if (fundType !== "All") params.set("fund_type", fundType);
    return fetchApi<{
      quarter: string;
      fund_type: string;
      rank_by: string;
      changes: Record<QuarterlyChangeType, QuarterlyChange[]>;
    }>(`/quarterly-changes?${params.toString()}`);
  },
};
