import type { MonitorSnapshot, ProviderCredit, UserStats } from "./types";

function isoMinutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

export function demoProviders(): ProviderCredit[] {
  const updatedAt = new Date().toISOString();
  return [
    {
      id: "openai",
      name: "OpenAI / GPT",
      status: "demo",
      currency: "USD",
      remaining: 62.4,
      consumed: 37.6,
      budget: 100,
      note: "Demo: monthly budget minus costs.",
      updatedAt,
    },
    {
      id: "xai",
      name: "xAI / Grok",
      status: "demo",
      currency: "USD",
      remaining: 148.2,
      consumed: null,
      budget: null,
      note: "Demo: prepaid management-API balance.",
      updatedAt,
    },
    {
      id: "deepseek",
      name: "DeepSeek",
      status: "warning",
      currency: "USD",
      remaining: 8.76,
      consumed: null,
      budget: null,
      note: "Demo: low balance warning.",
      updatedAt,
    },
    {
      id: "qwen",
      name: "Qwen / DashScope",
      status: "demo",
      currency: "USD",
      remaining: 214.5,
      consumed: 41.2,
      budget: 500,
      note: "Demo: available + monthly spend.",
      updatedAt,
    },
  ];
}

export function demoUsers(): UserStats {
  return {
    status: "demo",
    totalUsers: 1284,
    latestUser: {
      id: "usr_demo_9f2a",
      email: "maya@example.com",
      createdAt: isoMinutesAgo(2),
    },
    note: "Demo Supabase user pulse. Connect real credentials to go live.",
    updatedAt: new Date().toISOString(),
  };
}

export function demoSnapshot(): MonitorSnapshot {
  return {
    providers: demoProviders(),
    users: demoUsers(),
    lowBalanceThreshold: Number(process.env.LOW_BALANCE_THRESHOLD ?? 10),
    demoMode: true,
    fetchedAt: new Date().toISOString(),
  };
}
