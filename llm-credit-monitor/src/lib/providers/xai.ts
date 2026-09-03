import type { ProviderCredit } from "../types";

interface ValidationResponse {
  scopeId?: string;
  scope?: string;
  teamId?: string;
}

interface BalanceResponse {
  total?: { val?: string };
}

async function resolveTeamId(managementKey: string): Promise<string> {
  const configured = process.env.XAI_TEAM_ID?.trim();
  if (configured) return configured;

  const res = await fetch(
    "https://management-api.x.ai/auth/management-keys/validation",
    {
      headers: { Authorization: `Bearer ${managementKey}` },
      cache: "no-store",
    },
  );

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Team lookup failed HTTP ${res.status}: ${body.slice(0, 200)}`);
  }

  const data = (await res.json()) as ValidationResponse;
  const teamId = data.teamId ?? data.scopeId;
  if (!teamId) {
    throw new Error("Could not resolve XAI_TEAM_ID from management key; set XAI_TEAM_ID explicitly.");
  }
  return teamId;
}

export async function fetchXAICredit(): Promise<ProviderCredit> {
  const base: Omit<ProviderCredit, "status" | "remaining" | "consumed" | "budget" | "note" | "error"> = {
    id: "xai",
    name: "xAI / Grok",
    currency: "USD",
    updatedAt: new Date().toISOString(),
  };

  const key = process.env.XAI_MANAGEMENT_KEY?.trim();
  if (!key) {
    return {
      ...base,
      status: "unconfigured",
      remaining: null,
      consumed: null,
      budget: null,
      note: "Set XAI_MANAGEMENT_KEY (Management API key) to load prepaid balance.",
    };
  }

  try {
    const teamId = await resolveTeamId(key);
    const res = await fetch(
      `https://management-api.x.ai/v1/billing/teams/${teamId}/prepaid/balance`,
      {
        headers: { Authorization: `Bearer ${key}` },
        cache: "no-store",
      },
    );

    if (!res.ok) {
      const body = await res.text();
      throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
    }

    const data = (await res.json()) as BalanceResponse;
    const raw = data.total?.val;
    if (raw == null || raw === "") {
      throw new Error("Balance response missing total.val");
    }

    const cents = Number(raw);
    if (!Number.isFinite(cents)) {
      throw new Error(`Unparseable balance value: ${raw}`);
    }

    // Inverted ledger: top-ups are negative cents → remaining dollars = -cents / 100
    const remaining = -cents / 100;
    const threshold = Number(process.env.LOW_BALANCE_THRESHOLD ?? 10);

    return {
      ...base,
      status: remaining <= threshold ? "warning" : "ok",
      remaining,
      consumed: null,
      budget: null,
      note: "Prepaid ledger balance from xAI Management API (posted balance).",
    };
  } catch (err) {
    return {
      ...base,
      status: "error",
      remaining: null,
      consumed: null,
      budget: null,
      note: "Failed to query xAI prepaid balance.",
      error: err instanceof Error ? err.message : String(err),
    };
  }
}
