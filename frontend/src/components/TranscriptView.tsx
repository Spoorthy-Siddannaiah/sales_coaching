import { useEffect, useRef } from "react";
import { transcriptTurns } from "../evidenceNavigation";
import { date } from "../api";
import type { Conversation } from "../types";
export default function TranscriptView({ record, active, highlight }: { record: Conversation; active: boolean; highlight: { id: string; quote: string; version: string } | null }) {
  const transcript = record.transcript;
  const root = useRef<HTMLElement>(null);
  const turns = transcriptTurns(transcript);
  useEffect(() => {
    if (!active || !highlight || highlight.version !== transcript?.id) return;
    const target = root.current?.querySelector<HTMLElement>(`[data-source-id="${highlight.id}"]`);
    target?.scrollIntoView({ block: "center" });
    target?.focus({ preventScroll: true });
  }, [active, highlight, transcript?.id]);
  const recording = transcript?.source_metadata.meeting_metadata?.recording;
  return (
    <section ref={root} className="panel transcript-panel">
      <div className="section-title">
        <h3>Original transcript</h3>
        <span className="subtle">
          {transcript?.original_text.length.toLocaleString() || 0} characters
        </span>
      </div>
      <dl className="source-details">
        <div>
          <dt>Source ID</dt>
          <dd>{record.source_id}</dd>
        </div>
        <div>
          <dt>Speakers</dt>
          <dd>
            {transcript?.turns.length
              ? `${transcript.turns.length} verified salesperson/customer turns`
              : "Speaker attribution unavailable"}
          </dd>
        </div>
        <div>
          <dt>Timing</dt>
          <dd>
            {recording?.start_time
              ? `Recording started ${date(recording.start_time)}. `
              : ""}
            {recording?.end_time ? `Ended ${date(recording.end_time)}. ` : ""}
            Per-turn timestamps unavailable.
          </dd>
        </div>
        {transcript?.source_metadata.license && (
          <div>
            <dt>License</dt>
            <dd>{transcript.source_metadata.license}</dd>
          </div>
        )}
      </dl>
      {!!transcript?.warnings.length && (
        <details className="source-warnings" open>
          <summary>Source limitations</summary>
          {transcript.warnings.map((warning, i) => (
            <p className="warning" key={i}>
              {warning}
            </p>
          ))}
        </details>
      )}
      <p className="field-help">
        Original text is preserved. No speaker identities or timestamps have
        been inferred.
      </p>
      <div className="transcript-turns">
        {turns.map(turn => {
          const selected = !!highlight && highlight.version === transcript?.id && highlight.id === turn.id;
          const at = selected && highlight ? turn.text.indexOf(highlight.quote) : -1;
          return <article key={turn.id} data-source-id={turn.id} className={`source-turn ${selected ? "source-highlight" : ""}`} tabIndex={-1}>
            <span className="source-turn-label">{turn.role || "Speaker unknown"} · {turn.id}</span>
            <pre className="source-turn-text">{at >= 0 && highlight ? <>{turn.text.slice(0, at)}<mark>{highlight.quote}</mark>{turn.text.slice(at + highlight.quote.length)}</> : turn.text}</pre>
          </article>;
        })}
      </div>
      <details><summary>Complete original text</summary><pre className="transcript-text" tabIndex={0} aria-label="Original transcript text">{transcript?.original_text || "No transcript saved."}</pre></details>
    </section>
  );
}
