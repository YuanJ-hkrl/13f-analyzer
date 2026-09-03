"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { MonitorSnapshot } from "@/lib/types";
import { AlertStack } from "@/components/AlertStack";
import { ProviderGrid } from "@/components/ProviderGrid";
import { UserPulse } from "@/components/UserPulse";

const DEFAULT_POLL_MS = 30_000;

type Alert = {
  id: string;
  title: string;
  body: string;
  tone: "user" | "balance";
};

export function Dashboard() {
  const [snapshot, setSnapshot] = useState<MonitorSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const lastUserCount = useRef<number | null>(null);
  const primed = useRef(false);
  const lowBalanceSeen = useRef<Set<string>>(new Set());

  const pushAlert = useCallback(
    (title: string, body: string, tone: "user" | "balance") => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      setAlerts((prev) => [{ id, title, body, tone }, ...prev].slice(0, 6));
    },
    [],
  );

  const dismissAlert = useCallback((id: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/monitor", { cache: "no-store" });
      if (!res.ok) {
        throw new Error(`Monitor API HTTP ${res.status}`);
      }
      const data = (await res.json()) as MonitorSnapshot;
      setSnapshot(data);
      setError(null);

      const count = data.users.totalUsers;
      if (count != null) {
        if (
          primed.current &&
          lastUserCount.current != null &&
          count > lastUserCount.current
        ) {
          const delta = count - lastUserCount.current;
          const latest = data.users.latestUser;
          pushAlert(
            delta === 1
              ? "New user registered"
              : `${delta} new users registered`,
            latest?.email
              ? `${latest.email} · total ${count}`
              : latest
                ? `Latest id ${latest.id} · total ${count}`
                : `User count is now ${count}`,
            "user",
          );
        }
        lastUserCount.current = count;
        primed.current = true;
      }

      for (const provider of data.providers) {
        if (
          provider.remaining != null &&
          provider.remaining <= data.lowBalanceThreshold
        ) {
          if (!lowBalanceSeen.current.has(provider.id)) {
            lowBalanceSeen.current.add(provider.id);
            pushAlert(
              `${provider.name} running low`,
              `${provider.remaining.toFixed(2)} ${provider.currency} remaining (threshold ${data.lowBalanceThreshold}).`,
              "balance",
            );
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [pushAlert]);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => {
      void load();
    }, DEFAULT_POLL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const simulateSignup = useCallback(() => {
    if (!snapshot) return;
    const nextCount = (snapshot.users.totalUsers ?? 0) + 1;
    const createdAt = new Date().toISOString();
    const email = `user${nextCount}@example.com`;

    setSnapshot({
      ...snapshot,
      users: {
        ...snapshot.users,
        totalUsers: nextCount,
        latestUser: {
          id: `usr_sim_${nextCount}`,
          email,
          createdAt,
        },
        updatedAt: createdAt,
      },
      fetchedAt: createdAt,
    });

    if (primed.current && lastUserCount.current != null) {
      pushAlert(
        "New user registered",
        `${email} · total ${nextCount}`,
        "user",
      );
    }
    lastUserCount.current = nextCount;
    primed.current = true;
  }, [pushAlert, snapshot]);

  return (
    <div className="shell">
      <header className="hero">
        <div className="hero-copy">
          <p className="brand">Flux</p>
          <h1 className="headline">Credit pulse for every model key.</h1>
          <p className="lede">
            Live balances across OpenAI, Grok, DeepSeek, and Qwen — plus a
            Supabase user count with registration alerts.
          </p>
          <div className="cta-row">
            <button
              type="button"
              className="btn-primary"
              onClick={() => void load()}
            >
              Refresh now
            </button>
            {snapshot?.demoMode ? (
              <button
                type="button"
                className="btn-ghost"
                onClick={simulateSignup}
              >
                Simulate signup
              </button>
            ) : null}
            <span className="meta-chip">
              {snapshot?.demoMode ? "Demo mode" : "Live keys"}
              {snapshot
                ? ` · updated ${new Date(snapshot.fetchedAt).toLocaleTimeString()}`
                : ""}
            </span>
          </div>
        </div>
        <div className="hero-orb" aria-hidden="true" />
      </header>

      <AlertStack alerts={alerts} onDismiss={dismissAlert} />

      {error ? <p className="error-banner">{error}</p> : null}
      {loading && !snapshot ? (
        <p className="loading-line">Gathering provider balances…</p>
      ) : null}

      {snapshot ? (
        <>
          <UserPulse users={snapshot.users} />
          <ProviderGrid
            providers={snapshot.providers}
            threshold={snapshot.lowBalanceThreshold}
          />
        </>
      ) : null}
    </div>
  );
}
