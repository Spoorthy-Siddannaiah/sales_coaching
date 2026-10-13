import { date, source } from "../api";
import type { ConversationSummary } from "../types";
export default function ConversationList({
  rows,
  selected,
  expanded,
  onToggle,
  onImport,
  onSelect,
}: {
  rows: ConversationSummary[];
  selected: string | null;
  expanded: boolean;
  onToggle: () => void;
  onImport: () => void;
  onSelect: (id: string) => void;
}) {
  return (
    <aside className="library" aria-label="Conversation navigation">
      <div className="library-heading">
        <h2>
          Conversations <span className="count">{rows.length}</span>
        </h2>
        <button
          className="mobile-toggle secondary"
          aria-expanded={expanded}
          aria-controls="conversation-list"
          onClick={onToggle}
        >
          {expanded ? "Hide list" : "Show list"}
        </button>
      </div>
      <button className="import-trigger" onClick={onImport}>
        <span aria-hidden="true">＋</span> Import meeting
      </button>
      <nav
        id="conversation-list"
        className={
          expanded ? "conversation-list expanded" : "conversation-list"
        }
        aria-label="Saved conversations"
      >
        {rows.length === 0 ? (
          <p className="muted empty">
            Import a meeting or load an offline demo to get started.
          </p>
        ) : (
          rows.map((row) => (
            <button
              className={
                "conversation-card " + (selected === row.id ? "selected" : "")
              }
              key={row.id}
              aria-current={selected === row.id ? "true" : undefined}
              onClick={() => onSelect(row.id)}
            >
              <span className="source-label">{source(row.provider)}</span>
              <strong>{row.title}</strong>
              <span className="card-bottom">
                <small>{date(row.created_at)}</small>
                <span className={"status-text " + row.analysis_status}>
                  {row.analysis_status === "failed"
                    ? "Analysis failed"
                    : row.analysis_status === "ready"
                      ? "Transcript saved"
                      : row.analysis_status === "completed"
                        ? "Report saved"
                        : row.analysis_status}
                </span>
              </span>
            </button>
          ))
        )}
      </nav>
      <p className="sidebar-note">
        Local workspace
        <br />
        Use approved test conversations.
      </p>
    </aside>
  );
}
