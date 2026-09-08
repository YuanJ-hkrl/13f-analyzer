import type { ProviderCredit } from "../types";

function monthStartUnix(): number {
  const now = new Date();
  return Math.floor(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1) / 1000,
  );
}

export async function fetchOpenAICredit(): Promise<ProviderCredit> {
  const base: Omit<ProviderCredit, "status" | "remaining" | "consumed" | "budget" | "note" | "error"> = {
    id: "openai",
    name: "OpenAI / GPT",
    currency: "USD",
    updatedAt: new Date().toISOString(),
  };

  const adminKey = process.env.OPENAI_ADMIN_KEY?.trim();
  const budgetRaw = process.env.OPENAI_MONTHLY_BUDGET?.trim();
  const budget = budgetRaw ? Number(budgetRaw) : null;

  if (!adminKey) {
    return {
      ...base,
      status: "unconfigured",
      remaining: null,
      consumed: null,
      budget,
      note: "Set OPENAI_ADMIN_KEY (Admin API key) to load monthly spend.",
    };
  }

  try {
    const start = monthStartUnix();
    const url = new URL("https://api.openai.com/v1/organization/costs");
    url.searchParams.set("start_time", String(start));
    url.searchParams.set("limit", "31");

    const res = await fetch(url, {
      headers: {
        Authorization: `Bearer ${adminKey}`,
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });

    if (!res.ok) {
      const body = await res.text();
      throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
    }

    const data = (await res.json()) as {
      data?: Array<{
        results?: Array<{ amount?: { value?: number; currency?: string } }>;
      }>;
    };

    let consumed = 0;
    let currency = "USD";
    for (const bucket of data.data ?? []) {
      for (const row of bucket.results ?? []) {
        consumed += row.amount?.value ?? 0;
        if (row.amount?.currency) {
          currency = row.amount.currency.toUpperCase();
        }
      }
    }

    const remaining =
      budget != null && Number.isFinite(budget) ? Math.max(0, budget - consumed) : null;

    return {
      ...base,
      currency,
      status: remaining != null && remaining <= Number(process.env.LOW_BALANCE_THRESHOLD ?? 10)
        ? "warning"
        : "ok",
      remaining,
      consumed,
      budget,
      note:
        remaining != null
          ? "Remaining = OPENAI_MONTHLY_BUDGET − month-to-date costs (Admin Costs API)."
          : "Month-to-date spend from Admin Costs API. Set OPENAI_MONTHLY_BUDGET to estimate remaining.",
    };
  } catch (err) {
    return {
      ...base,
      status: "error",
      remaining: null,
      consumed: null,
      budget,
      note: "Failed to query OpenAI organization costs.",
      error: err instanceof Error ? err.message : String(err),
    };
  }
}
