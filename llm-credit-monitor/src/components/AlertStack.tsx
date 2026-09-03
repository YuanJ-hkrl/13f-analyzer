"use client";

type Alert = {
  id: string;
  title: string;
  body: string;
  tone: "user" | "balance";
};

export function AlertStack({
  alerts,
  onDismiss,
}: {
  alerts: Alert[];
  onDismiss: (id: string) => void;
}) {
  if (alerts.length === 0) return null;

  return (
    <div className="alert-stack" role="region" aria-label="Alerts">
      {alerts.map((alert) => (
        <div
          key={alert.id}
          className={`alert-item alert-${alert.tone}`}
          role="status"
        >
          <div>
            <p className="alert-title">{alert.title}</p>
            <p className="alert-body">{alert.body}</p>
          </div>
          <button
            type="button"
            className="alert-dismiss"
            onClick={() => onDismiss(alert.id)}
            aria-label="Dismiss alert"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
