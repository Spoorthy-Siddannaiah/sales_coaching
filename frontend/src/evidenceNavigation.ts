import type { Conversation, Evidence, Role } from "./types";
export type SourceTurn = { id: string; role: Role; text: string; start: number; end: number };
export function transcriptTurns(transcript: Conversation["transcript"]): SourceTurn[] {
  if (!transcript) return [];
  if (transcript.turns.length) return transcript.turns.map((turn, index) => ({
    id: `t${String(index + 1).padStart(4, "0")}`, role: turn.role,
    text: Array.from(transcript.original_text).slice(turn.start, turn.end).join(""), start: turn.start, end: turn.end,
  }));
  let start = 0;
  return (transcript.original_text.match(/.*?(?:\r\n|[\n\r\v\f\u001c-\u001e\u0085\u2028\u2029]|$)/gs) || []).flatMap((text, index) => {
    const offset = start; start += text.length;
    return text.trim() ? [{ id: `t${String(index + 1).padStart(4, "0")}`, role: null, text, start: offset, end: start }] : [];
  });
}
// Historical reports persist exact quote+role, not IDs. Resolve only a unique
// exact match in the same transcript version; never normalize or guess.
export function evidenceTarget(evidence: Evidence, turns: SourceTurn[]): SourceTurn | null {
  const matches = turns.filter(turn => turn.role === evidence.role && turn.text.includes(evidence.quote) && evidence.quote.trim());
  return matches.length === 1 ? matches[0] : null;
}
