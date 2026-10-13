import type { Analysis, Conversation, Evidence } from "../types";
import { evidenceTarget, transcriptTurns } from "../evidenceNavigation";
import CoachingReportView from "./CoachingReportView";

export default function CoachingWorkspace({ record, analysis, onEvidence }: {
  record: Conversation; analysis: Analysis; onEvidence: (item: Evidence) => void;
}) {
  const turns = transcriptTurns(record.transcript);
  const sameVersion = record.transcript?.id === analysis.transcript_version_id;
  return analysis.report ? <>
    {!sameVersion && <p className="warning">This report used an earlier transcript version. Its source is unavailable in the current transcript; evidence navigation is disabled.</p>}
    <CoachingReportView report={analysis.report} analysis={analysis} sourceLabel={record.provider === "offline_fixture" ? "Offline synthetic fixture" : "Notion AI Meeting Notes"}
      onEvidence={onEvidence} evidenceReference={item => sameVersion ? evidenceTarget(item, turns)?.id || null : null} />
  </> : null;
}
