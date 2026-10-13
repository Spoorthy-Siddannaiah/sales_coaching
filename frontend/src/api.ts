import type {
  Analysis,
  Context,
  Conversation,
  ConversationSummary,
  Runtime,
} from "./types";
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch {
    throw new Error(
      "Cannot reach the backend. Check that FastAPI is running on port 8000.",
    );
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.message ||
            (Array.isArray(detail)
              ? "Check required fields and their lengths."
              : `Request failed (${response.status}).`),
    );
  }
  return data as T;
}
export const api = {
  list: () => request<ConversationSummary[]>("/conversations"),
  detail: (id: string) => request<Conversation>("/conversations/" + id),
  runtime: () => request<Runtime>("/runtime"),
  notion: (page: string) =>
    request<{ conversation: { id: string }; reused: boolean }>(
      "/imports/notion",
      { method: "POST", body: JSON.stringify({ page }) },
    ),
  fixture: () =>
    request<{ conversation: Conversation; reused: boolean }>(
      "/imports/fixture",
      { method: "POST", body: JSON.stringify({ fixture: "kapibala" }) },
    ),
  context: (id: string, value: Context) =>
    request<Context>(`/conversations/${id}/context`, {
      method: "PUT",
      body: JSON.stringify(value),
    }),
  start: (id: string, requestId: string, allowPaid: boolean) =>
    request<Analysis>(`/conversations/${id}/analyses`, {
      method: "POST",
      body: JSON.stringify({ request_id: requestId, allow_paid: allowPaid }),
    }),
  analysis: (id: string) => request<Analysis>("/analyses/" + id),
};
export function date(value: string): string {
  return new Date(value).toLocaleString();
}
export function source(provider: string): string {
  return provider === "notion"
    ? "Native Notion meeting"
    : "Offline synthetic fixture";
}
