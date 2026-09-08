import type { ProviderCredit } from "../types";

interface BalanceInfo {
  currency?: string;
  total_balance?: string;
  granted_balance?: string;
  topped_up_balance?: string;
}

interface BalanceResponse {
  is_available?: boolean;
  balance_infos?: BalanceInfo[];
}

export async function fetchDeepSeekCredit(): Promise<ProviderCredit> {
  const base: Omit<ProviderCredit, "status" | "remaining" | "consumed" | "budget" | "note" | "error"> = {
    id: "deepseek",
    name: "DeepSeek",
    currency: "USD",
    updatedAt: new Date().toISOString(),
  };

  const key = process.env.DEEPSEEK_API_KEY?.trim();
  if (!key) {
    return {
      ...base,
      status: "unconfigured",
      remaining: null,
      consumed: null,
      budget: null,
      note: "Set DEEPSEEK_API_KEY to load account balance.",
    };
  }

  try {
    const res = await fetch("https://api.deepseek.com/user/balance", {
      headers: { Authorization: `Bearer ${key}` },
      cache: "no-store",
    });

    if (!res.ok) {
      const body = await res.text();
      throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
    }

    const data = (await res.json()) as BalanceResponse;
    const info = data.balance_infos?.[0];
    if (!info) {
      throw new Error("No balance_infos returned");
    }

    const remaining = Number(info.total_balance ?? 0);
    const granted = Number(info.granted_balance ?? 0);
    const topped = Number(info.topped_up_balance ?? 0);
    const currency = (info.currency ?? "USD").toUpperCase();
    const threshold = Number(process.env.LOW_BALANCE_THRESHOLD ?? 10);

    return {
      ...base,
      currency,
      status:
        data.is_available === false || remaining <= threshold ? "warning" : "ok",
      remaining,
      consumed: null,
      budget: null,
      note: `Granted ${granted.toFixed(2)} + topped-up ${topped.toFixed(2)} ${currency}.`,
    };
  } catch (err) {
    return {
      ...base,
      status: "error",
      remaining: null,
      consumed: null,
      budget: null,
      note: "Failed to query DeepSeek /user/balance.",
      error: err instanceof Error ? err.message : String(err),
    };
  }
}
