export type ProviderId = "openai" | "xai" | "deepseek" | "qwen";

export type ProviderStatus = "ok" | "warning" | "error" | "unconfigured" | "demo";

export interface ProviderCredit {
  id: ProviderId;
  name: string;
  status: ProviderStatus;
  currency: string;
  /** Remaining / available balance when known */
  remaining: number | null;
  /** Spend in the current window (month / billing period) when known */
  consumed: number | null;
  /** Configured or reported budget / total when known */
  budget: number | null;
  /** Short human-readable note (e.g. how remaining was derived) */
  note: string;
  error?: string;
  updatedAt: string;
}

export interface UserStats {
  status: ProviderStatus;
  totalUsers: number | null;
  latestUser?: {
    id: string;
    email?: string | null;
    createdAt: string;
  } | null;
  note: string;
  error?: string;
  updatedAt: string;
}

export interface MonitorSnapshot {
  providers: ProviderCredit[];
  users: UserStats;
  lowBalanceThreshold: number;
  demoMode: boolean;
  fetchedAt: string;
}
