// No server/provider requests: verify messages consumed by React's existing alerts.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const code = ts.transpileModule(readFileSync(new URL("../src/api.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { api } = await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));
const originalFetch = globalThis.fetch;
try {
  const limited = "Notion rate limited the request. Wait before retrying.";
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: { code: "notion_rate_limited", message: limited } }), { status: 429 });
  await assert.rejects(api.notion("test-page"), { message: limited });
  const oversized = "The complete transcript is saved (20,000 characters), but coaching supports at most 16,000 characters. No analysis was started or paid call made. View the full transcript in Transcript. Use a shorter meeting for coaching; this prototype does not split or truncate transcripts.";
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: oversized }), { status: 422 });
  await assert.rejects(api.start("test-conversation", "test-request", false), { message: oversized });
  console.log("PASS: safe Notion errors and actionable oversized-transcript messages reach the frontend unchanged; no network calls.");
} finally {
  globalThis.fetch = originalFetch;
}
