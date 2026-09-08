import { demoSnapshot } from "./demo";
import { fetchDeepSeekCredit } from "./providers/deepseek";
import { fetchOpenAICredit } from "./providers/openai";
import { fetchQwenCredit } from "./providers/qwen";
import { fetchXAICredit } from "./providers/xai";
import { fetchUserStats } from "./supabase";
import type { MonitorSnapshot } from "./types";

export function isDemoMode(): boolean {
  const flag = process.env.DEMO_MODE?.trim().toLowerCase();
  if (flag === "true" || flag === "1") return true;
  if (flag === "false" || flag === "0") return false;

  // Auto-demo when nothing is configured yet
  const hasAnyKey = Boolean(
    process.env.OPENAI_ADMIN_KEY?.trim() ||
      process.env.XAI_MANAGEMENT_KEY?.trim() ||
      process.env.DEEPSEEK_API_KEY?.trim() ||
      process.env.DASHSCOPE_API_KEY?.trim() ||
      (process.env.NEXT_PUBLIC_SUPABASE_URL?.trim() &&
        process.env.SUPABASE_SERVICE_ROLE_KEY?.trim()),
  );
  return !hasAnyKey;
}

export async function collectMonitorSnapshot(): Promise<MonitorSnapshot> {
  if (isDemoMode()) {
    return demoSnapshot();
  }

  const [openai, xai, deepseek, qwen, users] = await Promise.all([
    fetchOpenAICredit(),
    fetchXAICredit(),
    fetchDeepSeekCredit(),
    fetchQwenCredit(),
    fetchUserStats(),
  ]);

  return {
    providers: [openai, xai, deepseek, qwen],
    users,
    lowBalanceThreshold: Number(process.env.LOW_BALANCE_THRESHOLD ?? 10),
    demoMode: false,
    fetchedAt: new Date().toISOString(),
  };
}
