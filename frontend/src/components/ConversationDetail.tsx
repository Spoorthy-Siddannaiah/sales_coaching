import { useEffect, useRef, useState } from "react";
import { api, date, source } from "../api";
import type { Analysis, Conversation, Evidence, Runtime } from "../types";
import { evidenceTarget, transcriptTurns } from "../evidenceNavigation";
import ContextForm from "./ContextForm";
import CoachingWorkspace from "./CoachingWorkspace";
import TranscriptView from "./TranscriptView";
import AnalysisControls from "./AnalysisControls";
import AnalysisHistory from "./AnalysisHistory";
type Tab = "overview" | "transcript" | "coaching" | "history";
const tabs: Tab[] = ["overview", "transcript", "coaching", "history"];
export default function ConversationDetail({
  record,
  runtime,
  onRefresh,
}: {
  record: Conversation;
  runtime: Runtime | null;
  onRefresh: () => Promise<void>;
}) {
  const [analysis, setAnalysis] = useState<Analysis | null>(
    record.analyses[0] || null,
  );
  const [selectedId, setSelectedId] = useState(record.analyses[0]?.id || "");
  const [tab, setTab] = useState<Tab>("overview");
  const [highlight, setHighlight] = useState<{ id: string; quote: string; version: string } | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [allowPaid, setAllowPaid] = useState(false);
  const requestId = useRef<string | null>(null);
  useEffect(() => {
    setAnalysis(
      record.analyses.find((a) => a.id === selectedId) ||
        record.analyses[0] ||
        null,
    );
  }, [record, selectedId]);
  const active =
    record.analyses.some(
      (a) => a.status === "pending" || a.status === "analyzing",
    ) ||
    analysis?.status === "pending" ||
    analysis?.status === "analyzing";
  const runningId =
    record.analyses.find((a) => ["pending", "analyzing"].includes(a.status))
      ?.id ||
    (analysis && ["pending", "analyzing"].includes(analysis.status)
      ? analysis.id
      : null);
  useEffect(() => {
    if (!runningId) return;
    const id = runningId;
    let stopped = false;
    const timer = window.setInterval(() => {
      api
        .analysis(id)
        .then((next) => {
          if (stopped) return;
          if (selectedId === id) setAnalysis(next);
          if (next.status === "completed" || next.status === "failed") {
            window.clearInterval(timer);
            void onRefresh().catch((e) => setError((e as Error).message));
          }
        })
        .catch((e) => {
          if (!stopped) setError((e as Error).message);
        });
    }, 900);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [runningId, selectedId, onRefresh]);
  async function start() {
    setBusy(true);
    setError("");
    // Keep the same ID if the response is uncertain. A deliberate new analysis
    // gets a new ID only after this request is acknowledged.
    requestId.current ??= crypto.randomUUID();
    try {
      const next = await api.start(record.id, requestId.current, allowPaid);
      requestId.current = null;
      setSelectedId(next.id);
      setAnalysis(next);
      setAllowPaid(false);
      setTab("coaching");
      await onRefresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function switchTab(next: Tab, focus = false) {
    setTab(next);
    if (focus) document.getElementById(`tab-${next}`)?.focus();
  }
  const verified =
    record.provider === "offline_fixture" && !!record.transcript?.turns.length;
  return (
    <main className="detail">
      <header className="detail-header">
        <div>
          <div className="conversation-meta">
            <span>{source(record.provider)}</span>
            <span aria-hidden="true">·</span>
            <span>Saved {date(record.created_at)}</span>
          </div>
          <h2>{record.title}</h2>
          <p className="muted">
            {verified
              ? `${record.transcript?.turns.length} verified salesperson/customer turns`
              : "Speaker attribution unavailable"}
          </p>
        </div>
      </header>
      {record.provider === "offline_fixture" && (
        <p className="fixture-notice">
          Synthetic offline demo · {record.transcript?.source_metadata.license}.
          Not a connected Notion meeting.
        </p>
      )}
      <div className="tabs" role="tablist" aria-label="Conversation workspace">
        {tabs.map((item, index) => (
          <button
            key={item}
            id={`tab-${item}`}
            role="tab"
            aria-selected={tab === item}
            aria-controls={`panel-${item}`}
            tabIndex={tab === item ? 0 : -1}
            onClick={() => switchTab(item)}
            onKeyDown={(event) => {
              let next = index;
              if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
              else if (event.key === "ArrowLeft")
                next = (index + tabs.length - 1) % tabs.length;
              else if (event.key === "Home") next = 0;
              else if (event.key === "End") next = tabs.length - 1;
              else return;
              event.preventDefault();
              switchTab(tabs[next], true);
            }}
          >
            {item.charAt(0).toUpperCase() + item.slice(1)}
            {item === "coaching" && active && (
              <span className="processing-dot" aria-label="Analysis running" />
            )}
          </button>
        ))}
      </div>
      {/* Keep panels mounted so switching tabs preserves context edits and approval. */}
      <section
        id="panel-overview"
        role="tabpanel"
        aria-labelledby="tab-overview"
        hidden={tab !== "overview"}
        className="tab-panel"
      >
        <ContextForm
          value={record.customer_context}
          onDirty={setDirty}
          onSave={async (value) => {
            await api.context(record.id, value);
            await onRefresh();
          }}
        />
        <AnalysisControls
          record={record}
          runtime={runtime}
          dirty={dirty}
          busy={busy}
          active={!!active}
          allowPaid={allowPaid}
          error={error}
          onApproval={setAllowPaid}
          onStart={() => void start()}
          onView={() => switchTab("coaching")}
        />
      </section>
      <section
        id="panel-transcript"
        role="tabpanel"
        aria-labelledby="tab-transcript"
        hidden={tab !== "transcript"}
        className="tab-panel"
      >
        <TranscriptView record={record} active={tab === "transcript"} highlight={highlight} />
      </section>
      <section
        id="panel-coaching"
        role="tabpanel"
        aria-labelledby="tab-coaching"
        hidden={tab !== "coaching"}
        className="tab-panel"
      >
        <section className="panel analysis-panel">
          <div className="section-title">
            <h3>Coaching</h3>
            <button
              className="secondary compact"
              onClick={() => switchTab("overview", true)}
            >
              {active ? "View analysis setup" : "Set up analysis"}
            </button>
          </div>
          {!analysis && (
            <div className="coaching-empty">
              <h4>No coaching report yet</h4>
              <p>
                Review customer context, then authorize and start an analysis
                from Overview.
              </p>
              <button onClick={() => switchTab("overview", true)}>
                Analyze conversation
              </button>
            </div>
          )}
          {analysis && ["pending", "analyzing"].includes(analysis.status) && (
            <div className="analysis-status" role="status">
              <span className="processing-dot" />
              <div>
                <strong>
                  {analysis.status === "pending"
                    ? "Analysis queued"
                    : "Analysis in progress"}
                </strong>
                <p>
                  Generating and validating your report. Progress is saved; you
                  can switch tabs.
                </p>
              </div>
            </div>
          )}
          {analysis?.status === "failed" && (
            <div className="failure-state" role="status">
              <h4>
                {analysis.error_message?.includes("failed validation")
                  ? "Report did not pass evidence checks"
                  : "Analysis could not be completed"}
              </h4>
              <p>
                Your transcript is saved. This attempt produced no accepted
                report. No automatic retry was made.
              </p>
              <details>
                <summary>Failure details</summary>
                <p>{analysis.error_message}</p>
              </details>
    
              <p className="field-help">
                Paid responses can incur a charge even when rejected. A new
                attempt requires fresh authorization in Overview.
              </p>
            </div>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {analysis?.status === "completed" && analysis.report && (
            <>
              <p className="saved-report" role="status">
                Validated report saved in SQLite.
              </p>
              <CoachingWorkspace record={record} analysis={analysis} onEvidence={(item: Evidence) => {
                if (record.transcript?.id !== analysis.transcript_version_id) return;
                const target = evidenceTarget(item, transcriptTurns(record.transcript));
                if (target && record.transcript) {
                  setHighlight({ id: target.id, quote: item.quote, version: record.transcript.id });
                  switchTab("transcript");
                }
              }} />
            </>
          )}
        </section>
      </section>
      <section id="panel-history" role="tabpanel" aria-labelledby="tab-history" hidden={tab !== "history"} className="tab-panel">
        <section className="panel">
          <h3>Analysis history &amp; input details</h3>
          {!record.analyses.length && <p>No analyses saved yet.</p>}
          <AnalysisHistory
            record={record}
            analysis={analysis}
            selectedId={selectedId}
            onSelect={(id) => {
              setSelectedId(id);
              setError("");
              setHighlight(null);
            }}
          />


        </section>
      </section>
    </main>
  );
}
