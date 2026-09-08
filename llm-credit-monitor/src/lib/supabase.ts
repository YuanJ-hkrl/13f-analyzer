import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { UserStats } from "./types";

function getServiceClient(): SupabaseClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim();
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();
  if (!url || !key) return null;
  return createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export async function fetchUserStats(): Promise<UserStats> {
  const updatedAt = new Date().toISOString();
  const table = process.env.SUPABASE_USERS_TABLE?.trim() || "profiles";
  const client = getServiceClient();

  if (!client) {
    return {
      status: "unconfigured",
      totalUsers: null,
      latestUser: null,
      note: "Set NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
      updatedAt,
    };
  }

  try {
    const { count, error: countError } = await client
      .from(table)
      .select("*", { count: "exact", head: true });

    if (countError) {
      throw new Error(countError.message);
    }

    const { data: latestRows, error: latestError } = await client
      .from(table)
      .select("id, email, created_at")
      .order("created_at", { ascending: false })
      .limit(1);

    if (latestError) {
      // Table may not have email — fall back to id + created_at only
      const fallback = await client
        .from(table)
        .select("id, created_at")
        .order("created_at", { ascending: false })
        .limit(1);

      if (fallback.error) {
        throw new Error(fallback.error.message);
      }

      const row = fallback.data?.[0] as
        | { id: string; created_at: string }
        | undefined;

      return {
        status: "ok",
        totalUsers: count ?? 0,
        latestUser: row
          ? { id: row.id, email: null, createdAt: row.created_at }
          : null,
        note: `Counting rows in public.${table}.`,
        updatedAt,
      };
    }

    const row = latestRows?.[0] as
      | { id: string; email?: string | null; created_at: string }
      | undefined;

    return {
      status: "ok",
      totalUsers: count ?? 0,
      latestUser: row
        ? {
            id: row.id,
            email: row.email ?? null,
            createdAt: row.created_at,
          }
        : null,
      note: `Counting rows in public.${table}. New inserts trigger dashboard alerts.`,
      updatedAt,
    };
  } catch (err) {
    return {
      status: "error",
      totalUsers: null,
      latestUser: null,
      note: `Failed to query Supabase table "${table}".`,
      error: err instanceof Error ? err.message : String(err),
      updatedAt,
    };
  }
}
