import { date } from "../api";
import type { Analysis, Conversation } from "../types";
export default function AnalysisHistory({
  record,
  analysis,
  selectedId,
  onSelect,
}: {
  record: Conversation;
  analysis: Analysis | null;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  if (!record.analyses.length) return null;
  const stale =
    analysis &&
    JSON.stringify(analysis.customer_context) !==
      JSON.stringify(record.customer_context);
  return (
    <>
      <label className="history-label">
        Analysis history
        <select
          value={selectedId || record.analyses[0].id}
          onChange={(e) => onSelect(e.target.value)}
        >
          {record.analyses.map((a) => (
            <option key={a.id} value={a.id}>
              {date(a.created_at)} ·{" "}
              {a.status === "completed"
                ? "Report saved"
                : a.status === "failed"
                  ? "Failed attempt"
                  : a.status}
            </option>
          ))}
        </select>
      </label>
      {stale && (
        <p className="warning">
          This attempt uses a previous context snapshot. New analysis uses your
          current saved context.
        </p>
      )}
      {analysis && (
        <details className="snapshot">
          <summary>Input used for this attempt</summary>
          <dl>
            {Object.entries(analysis.customer_context).map(([key, value]) => (
              <div key={key}>
                <dt>{key.replaceAll("_", " ")}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <small>Transcript version: {analysis.transcript_version_id}</small>
          <p className="field-help">Model: {analysis.model} · Prompt: {analysis.provider_metadata?.prompt_version || "Unknown (historical attempt)"} · Validator: {analysis.provider_metadata?.validator_version || "Unknown (historical attempt)"}
            {analysis.latency_seconds !== null && ` · ${analysis.latency_seconds.toFixed(2)} seconds`}
            {analysis.provider_metadata?.estimated_cost_usd !== undefined && ` · Estimated $${analysis.provider_metadata.estimated_cost_usd.toFixed(6)}`}
          </p>
          {analysis.transcript_version_id !== record.transcript?.id && (
            <p className="warning">
              This attempt used an earlier transcript version.
            </p>
          )}
        </details>
      )}
    </>
  );
}
