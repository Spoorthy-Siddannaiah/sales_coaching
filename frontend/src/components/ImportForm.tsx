import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";

export default function ImportForm({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: (id: string, notice: string) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [page, setPage] = useState("");
  const [busy, setBusy] = useState<"notion" | "fixture" | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (open && !dialog.current?.open) {
      setError("");
      dialog.current?.showModal();
      dialog.current?.querySelector("input")?.focus();
    }
    if (!open) dialog.current?.close();
  }, [open]);
  async function run(fixture: boolean) {
    setBusy(fixture ? "fixture" : "notion");
    setError("");
    try {
      const result = fixture
        ? await api.fixture()
        : await api.notion(page.trim());
      const notice = fixture
        ? "Offline demo opened. Loading the transcript did not run an analysis."
        : result.reused
          ? "Meeting already saved. Opened the existing transcript."
          : "Meeting imported. Add customer context to generate coaching.";
      await onImported(result.conversation.id, notice);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    void run(false);
  }
  return (
    <dialog
      ref={dialog}
      className="import-dialog"
      aria-labelledby="import-title"
      onCancel={(event) => {
        if (busy) event.preventDefault();
        else onClose();
      }}
      onClose={onClose}
    >
      <div className="dialog-header">
        <div>
          <h2 id="import-title">Import meeting</h2>
          <p className="muted">
            Use an existing native Notion AI Meeting Notes transcript.
          </p>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="Close import dialog"
          disabled={!!busy}
          onClick={onClose}
        >
          ×
        </button>
      </div>
      <form onSubmit={submit}>
        <label htmlFor="notion-page">Notion page URL or ID</label>
        <input
          id="notion-page"
          autoFocus
          value={page}
          onChange={(e) => setPage(e.target.value)}
          placeholder="https://www.notion.so/…"
          required
          disabled={!!busy}
        />
        <p className="field-help">
          Grant your Notion connection access to the page before importing.
          Loading a transcript does not run paid analysis.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button
            type="button"
            className="secondary"
            onClick={onClose}
            disabled={!!busy}
          >
            Cancel
          </button>
          <button disabled={!!busy}>
            {busy === "notion" ? "Importing…" : "Import transcript"}
          </button>
        </div>
      </form>
      <div className="demo-option">
        <div>
          <h3>Try an offline demo</h3>
          <p className="muted">
            Licensed synthetic sales dialogue with verified roles. No Notion
            connection required; coaching uses the configured model.
          </p>
        </div>
        <button
          className="secondary"
          disabled={!!busy}
          onClick={() => void run(true)}
        >
          {busy === "fixture" ? "Loading…" : "Load offline demo"}
        </button>
      </div>
    </dialog>
  );
}
