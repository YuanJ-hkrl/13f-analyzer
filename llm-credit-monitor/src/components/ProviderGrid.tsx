import type { ProviderCredit } from "@/lib/types";

function money(value: number | null, currency: string): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency || "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function fillPercent(provider: ProviderCredit): number | null {
  if (provider.budget != null && provider.budget > 0) {
    const remaining = provider.remaining ?? Math.max(0, provider.budget - (provider.consumed ?? 0));
    return Math.max(0, Math.min(100, (remaining / provider.budget) * 100));
  }
  if (provider.remaining != null && provider.consumed != null) {
    const total = provider.remaining + provider.consumed;
    if (total > 0) return (provider.remaining / total) * 100;
  }
  return null;
}

export function ProviderGrid({
  providers,
  threshold,
}: {
  providers: ProviderCredit[];
  threshold: number;
}) {
  return (
    <section className="provider-section" aria-labelledby="providers-heading">
      <div className="section-head">
        <p className="section-kicker">Providers</p>
        <h2 id="providers-heading" className="section-title">
          Credit levels
        </h2>
        <p className="section-copy">
          Remaining vs consumed across your LLM keys. Warns under{" "}
          {money(threshold, "USD")}.
        </p>
      </div>

      <div className="provider-grid">
        {providers.map((provider) => {
          const pct = fillPercent(provider);
          return (
            <article
              key={provider.id}
              className={`provider-panel status-border-${provider.status}`}
            >
              <div className="provider-top">
                <h3 className="provider-name">{provider.name}</h3>
                <span className={`status-pill status-${provider.status}`}>
                  {provider.status}
                </span>
              </div>

              <p className="provider-remaining">
                {money(provider.remaining, provider.currency)}
              </p>
              <p className="provider-remaining-label">remaining</p>

              <div className="provider-metrics">
                <div>
                  <span className="metric-label">Consumed</span>
                  <span className="metric-value">
                    {money(provider.consumed, provider.currency)}
                  </span>
                </div>
                <div>
                  <span className="metric-label">Budget</span>
                  <span className="metric-value">
                    {money(provider.budget, provider.currency)}
                  </span>
                </div>
              </div>

              {pct != null ? (
                <div
                  className="meter"
                  role="meter"
                  aria-valuenow={Math.round(pct)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${provider.name} remaining percent`}
                >
                  <div className="meter-fill" style={{ width: `${pct}%` }} />
                </div>
              ) : (
                <div className="meter meter-empty" aria-hidden="true" />
              )}

              <p className="provider-note">{provider.note}</p>
              {provider.error ? (
                <p className="inline-error">{provider.error}</p>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
