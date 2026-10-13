import { useEffect, useState, type FormEvent } from "react";
import type { Context } from "../types";
const empty: Context = {
  company: "",
  relevant_needs: "",
  previous_interactions: "",
  objective: "",
};
export default function ContextForm({
  value,
  onSave,
  onDirty,
}: {
  value: Context | null;
  onSave: (value: Context) => Promise<void>;
  onDirty: (dirty: boolean) => void;
}) {
  const baseline = JSON.stringify(value || empty);
  const [draft, setDraft] = useState<Context>(value || empty);
  const [editing, setEditing] = useState(!value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const dirty = JSON.stringify(draft) !== baseline;
  // Polling returns fresh objects. Reset only when saved context actually changes,
  // so a processing-state refresh cannot erase edits in progress.
  useEffect(() => {
    setDraft(JSON.parse(baseline));
    onDirty(false);
  }, [baseline, onDirty]);
  function update(key: keyof Context, text: string) {
    const next = { ...draft, [key]: text };
    setDraft(next);
    setSaved(false);
    onDirty(JSON.stringify(next) !== baseline);
  }
  function cancel() {
    setDraft(value || empty);
    onDirty(false);
    setError("");
    setEditing(!value);
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSave(draft);
      setSaved(true);
      setEditing(false);
      onDirty(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel context-panel">
      <div className="section-title">
        <div>
          <h3>Customer context</h3>
          <p className="field-help">Fictional or approved test data</p>
        </div>
        {editing ? (
          <span className={dirty ? "edit-state unsaved" : "edit-state"}>
            {dirty ? "Unsaved changes" : "Editing context"}
          </span>
        ) : (
          <button
            className="secondary compact"
            onClick={() => {
              setEditing(true);
              setSaved(false);
            }}
          >
            Edit context
          </button>
        )}
      </div>
      {editing ? (
        <form onSubmit={submit} className="context-grid">
          <label>
            Company
            <input
              value={draft.company}
              maxLength={200}
              required
              onChange={(e) => update("company", e.target.value)}
              placeholder="Fictional company"
            />
          </label>
          <label>
            Meeting objective
            <input
              value={draft.objective}
              maxLength={2000}
              required
              onChange={(e) => update("objective", e.target.value)}
              placeholder="What should this conversation achieve?"
            />
          </label>
          <label>
            Relevant needs
            <textarea
              value={draft.relevant_needs}
              maxLength={1500}
              required
              onChange={(e) => update("relevant_needs", e.target.value)}
              placeholder="Needs, constraints and success criteria"
            />
          </label>
          <label>
            Previous interactions
            <textarea
              value={draft.previous_interactions}
              maxLength={1000}
              required
              onChange={(e) => update("previous_interactions", e.target.value)}
              placeholder="Use ‘None known’ if appropriate"
            />
          </label>
          <div className="context-actions">
            <button disabled={busy}>{busy ? "Saving…" : "Save context"}</button>
            {value && (
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={cancel}
              >
                Cancel edits
              </button>
            )}
          </div>
        </form>
      ) : (
        <dl className="context-readonly">
          <div>
            <dt>Company</dt>
            <dd>{value?.company}</dd>
          </div>
          <div>
            <dt>Meeting objective</dt>
            <dd>{value?.objective}</dd>
          </div>
          <div>
            <dt>Relevant needs</dt>
            <dd>{value?.relevant_needs}</dd>
          </div>
          <div>
            <dt>Previous interactions</dt>
            <dd>{value?.previous_interactions}</dd>
          </div>
        </dl>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {saved && (
        <p className="success" role="status">
          Context saved.
        </p>
      )}
    </section>
  );
}
