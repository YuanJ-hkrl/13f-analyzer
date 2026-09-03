import type { ProviderCredit } from "../types";

interface QuotasPayload {
  code?: string;
  message?: string;
  data?: {
    available?: number;
    credits?: number;
    spend_limit?: number;
    daily_spend?: number;
    monthly_spend?: number;
  };
}

export async function fetchQwenCredit(): Promise<ProviderCredit> {
  const base: Omit<ProviderCredit, "status" | "remaining" | "consumed" | "budget" | "note" | "error"> = {
    id: "qwen",
    name: "Qwen / DashScope",
    currency: "USD",
    updatedAt: new Date().toISOString(),
  };

  const key = process.env.DASHSCOPE_API_KEY?.trim();
  if (!key) {
    return {
      ...base,
      status: "unconfigured",
      remaining: null,
      consumed: null,
      budget: null,
      note: "Set DASHSCOPE_API_KEY to load Model Studio quotas / balance.",
    };
  }

  const baseUrl =
    process.env.DASHSCOPE_BASE_URL?.trim() ||
    "https://dashscope-intl.aliyuncs.com/api/v1";

  try {
    const res = await fetch(`${baseUrl.replace(/\/$/, "")}/quotas`, {
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });

    if (!res.ok) {
      const body = await res.text();
      throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
    }

    const data = (await res.json()) as QuotasPayload;
    if (data.code && data.code !== "Success") {
      throw new Error(data.message || `DashScope code ${data.code}`);
    }

    const available = data.data?.available;
    const credits = data.data?.credits;
    const remaining =
      typeof available === "number"
        ? available
        : typeof credits === "number"
          ? credits
          : null;
    const consumed =
      typeof data.data?.monthly_spend === "number"
        ? data.data.monthly_spend
        : typeof data.data?.daily_spend === "number"
          ? data.data.daily_spend
          : null;
    const budget =
      typeof data.data?.spend_limit === "number" ? data.data.spend_limit : null;
    const threshold = Number(process.env.LOW_BALANCE_THRESHOLD ?? 10);

    return {
      ...base,
      status:
        remaining != null && remaining <= threshold ? "warning" : "ok",
      remaining,
      consumed,
      budget,
      note: "DashScope /quotas available balance + period spend.",
    };
  } catch (err) {
    return {
      ...base,
      status: "error",
      remaining: null,
      consumed: null,
      budget: null,
      note: "Failed to query DashScope /quotas.",
      error: err instanceof Error ? err.message : String(err),
    };
  }
}
