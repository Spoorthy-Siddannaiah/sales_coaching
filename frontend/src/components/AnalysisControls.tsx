import type { Conversation, Runtime } from "../types";
export default function AnalysisControls({
  record,
  runtime,
  dirty,
  busy,
  active,
  allowPaid,
  error,
  onApproval,
  onStart,
  onView,
}: {
  record: Conversation;
  runtime: Runtime | null;
  dirty: boolean;
  busy: boolean;
  active: boolean;
  allowPaid: boolean;
  error: string;
  onApproval: (value: boolean) => void;
  onStart: () => void;
  onView: () => void;
}) {
  return (
    <section className="panel analysis-controls">
      <div className="section-title">
        <h3>Generate coaching</h3>
        <span className="subtle">{runtime?.model || "Loading model…"}</span>
      </div>
      <p className="muted">
        {record.transcript?.turns.length
          ? "Verified roles support full coaching with source evidence."
          : "Limited coaching: speaker roles are unknown, so salesperson scores remain unknown."}
      </p>
      {dirty && (
        <p className="warning">Save context changes before analyzing.</p>
      )}
      {!record.customer_context && (
        <p className="warning">Add customer context and an objective first.</p>
      )}
      {runtime?.paid_approval_required && (
        <label className="paid-approval">
          <input
            type="checkbox"
            checked={allowPaid}
            onChange={(e) => onApproval(e.target.checked)}
          />
          <span>
            Authorize one paid OpenAI request.
            <small>Budget checks apply. No automatic retry or repair.</small>
          </span>
        </label>
      )}
      <div className="control-actions">
        <button
          disabled={
            busy ||
            active ||
            dirty ||
            !record.customer_context ||
            !runtime ||
            (runtime.paid_approval_required && !allowPaid)
          }
          onClick={onStart}
        >
          {busy
            ? "Submitting…"
            : active
              ? "Analysis running…"
              : record.analyses.length
                ? "Run a new analysis"
                : "Start analysis"}
        </button>
        {record.analyses.length > 0 && (
          <button className="secondary" onClick={onView}>
            View coaching
          </button>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
