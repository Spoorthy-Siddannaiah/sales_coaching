import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Conversation, ConversationSummary, Runtime } from "./types";
import ImportForm from "./components/ImportForm";
import ConversationList from "./components/ConversationList";
import ConversationDetail from "./components/ConversationDetail";
export default function App() {
  const [rows, setRows] = useState<ConversationSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Conversation | null>(null);
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const selection = useRef(0);
  const refreshList = useCallback(async () => {
    setRows(await api.list());
  }, []);
  const select = useCallback(async (id: string) => {
    const version = ++selection.current;
    setSelected(id);
    setLoading(true);
    setError("");
    setDetail(null);
    setNavigationOpen(false);
    try {
      const next = await api.detail(id);
      if (selection.current === version) setDetail(next);
    } catch (e) {
      if (selection.current === version) setError((e as Error).message);
    } finally {
      if (selection.current === version) setLoading(false);
    }
  }, []);
  const refreshDetail = useCallback(async () => {
    if (!selected) return;
    const version = selection.current;
    const next = await api.detail(selected);
    if (version === selection.current) setDetail(next);
    await refreshList();
  }, [selected, refreshList]);
  useEffect(() => {
    Promise.all([refreshList(), api.runtime().then(setRuntime)]).catch((e) =>
      setError((e as Error).message),
    );
  }, [refreshList]);
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            S
          </span>
          <div>
            <h1>Sales Coach</h1>
            <span>AI-powered conversation coaching</span>
          </div>
        </div>
        <span className="local-label">
          <i aria-hidden="true" />
          Local workspace
        </span>
      </header>
      <div className="app-layout">
        <ConversationList
          rows={rows}
          selected={selected}
          expanded={navigationOpen}
          onToggle={() => setNavigationOpen(!navigationOpen)}
          onImport={() => setImportOpen(true)}
          onSelect={(id) => {
            setNotice("");
            void select(id);
          }}
        />
        <div className="workspace">
          {notice && (
            <div className="success workspace-notice" role="status">
              <span>{notice}</span>
              <button
                className="icon-button"
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                ×
              </button>
            </div>
          )}
          {error && (
            <p role="alert" className="error">
              {error}{" "}
              <button
                className="secondary"
                onClick={() => window.location.reload()}
              >
                Reload
              </button>
            </p>
          )}
          {loading ? (
            <main className="empty-detail" role="status">
              Loading conversation…
            </main>
          ) : detail ? (
            <ConversationDetail
              key={detail.id}
              record={detail}
              runtime={runtime}
              onRefresh={refreshDetail}
            />
          ) : (
            <main className="empty-detail">
              <h2>Select a conversation</h2>
              <p>
                Review a saved transcript or import a meeting to prepare
                coaching.
              </p>
              <button onClick={() => setImportOpen(true)}>
                Import meeting
              </button>
              <p className="field-help">
                You can also load a clearly labelled offline demo from the
                import dialog.
              </p>
            </main>
          )}
        </div>
      </div>
      <ImportForm
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={async (id, message) => {
          await refreshList();
          await select(id);
          setNotice(message);
        }}
      />
    </div>
  );
}
