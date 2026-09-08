import type { UserStats } from "@/lib/types";

function formatWhen(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function UserPulse({ users }: { users: UserStats }) {
  return (
    <section className="user-pulse" aria-labelledby="user-pulse-heading">
      <div className="user-pulse-main">
        <p className="section-kicker">Supabase</p>
        <h2 id="user-pulse-heading" className="section-title">
          User pulse
        </h2>
        <p className="section-copy">{users.note}</p>
      </div>
      <div className="user-pulse-stats">
        <div className="stat">
          <span className="stat-label">Total users</span>
          <span className="stat-value">
            {users.totalUsers == null ? "—" : users.totalUsers.toLocaleString()}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Latest signup</span>
          <span className="stat-value-sm">
            {users.latestUser?.email ?? users.latestUser?.id ?? "—"}
          </span>
          <span className="stat-sub">{formatWhen(users.latestUser?.createdAt)}</span>
        </div>
        <div className={`status-pill status-${users.status}`}>
          {users.status}
        </div>
      </div>
      {users.error ? <p className="inline-error">{users.error}</p> : null}
    </section>
  );
}
