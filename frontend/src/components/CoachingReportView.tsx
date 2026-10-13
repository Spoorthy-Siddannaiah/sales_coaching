import type { ReactNode } from "react";
import { date } from "../api";
import type { Analysis, Evidence, Finding, Report } from "../types";

const labels: Record<string, string> = {
  understanding_customer_needs: "Understanding customer needs",
  discovery_questions: "Discovery questions",
  value_explanation: "Explaining value",
  objection_handling: "Handling objections",
  next_step_clarity: "Securing next steps",
};
function Findings({ title, items, empty, renderEvidence }: { title: string; items: Finding[]; empty: string; renderEvidence?: (items: Evidence[]) => ReactNode }) {
  return <section><h4>{title}</h4>{items.length ? items.map((item, i) => <div key={i}><p>{item.text}</p>{renderEvidence?.(item.evidence)}</div>) : <p className="muted">{empty}</p>}</section>;
}
type EvidenceProps = { onEvidence: (item: Evidence) => void; evidenceReference: (item: Evidence) => string | null };
function EvidenceLinks({ items, onEvidence, evidenceReference }: EvidenceProps & { items: Evidence[] }) {
  return <span className="evidence-links">{items.map((item, index) => {
    const id = evidenceReference(item);
    return <button key={index} type="button" disabled={!id} onClick={() => onEvidence(item)} title={id ? `View original ${item.role || "unattributed"} source ${id}` : "No unique match in this transcript version"} aria-label={id ? `View evidence ${id}, ${item.role || "speaker unknown"}` : "Evidence unavailable for this transcript"}>{id || "Unavailable"}</button>;
  })}</span>;
}
export default function CoachingReportView({ report, analysis, onEvidence, evidenceReference, sourceLabel }: EvidenceProps & { report: Report; analysis: Analysis; sourceLabel: string }) {
  const links = (items: Evidence[]) => <EvidenceLinks items={items} onEvidence={onEvidence} evidenceReference={evidenceReference} />;
  return <div className="report dashboard-report">
    <div className="report-heading"><h3>Sales Coaching Report</h3><span className="badge">{report.mode === "full" ? "Verified roles" : "Roles unavailable"}</span></div>
    <p className="muted report-date">{analysis.customer_context.company} · {sourceLabel} · {date(analysis.created_at)} · Report saved</p>
    <p className="report-objective"><strong>Objective:</strong> {analysis.objective}</p>
    <div className="report-summary"><Findings title="Conversation summary" items={[report.summary]} empty="" renderEvidence={links} /></div>
    <section className="compact-outcome"><h4>Conversation outcome</h4><p>{report.outcome?.text || "No supported outcome reported."}</p>{report.outcome && links(report.outcome.evidence)}</section>
    <section><h4>Coaching scorecard</h4><div className="scorecard-grid">{Object.entries(report.dimensions).map(([key, item]) => <div className="scorecard dimension" key={key}>
      <h4>{labels[key]}</h4><span className="score">{item.score === null ? "Unknown" : `${item.score}/5`}</span><p>{item.reason}{links(item.evidence)}</p>
    </div>)}</div></section>
    <section><h4>Improve next time</h4><div className="compact-improvements">{report.improvements.map((item, i) => <article className="improvement" key={i}>
      <h4>{i + 1}. {item.suggestion}</h4><p>{item.why_it_matters}</p><small>AI recommendation — not spoken in the conversation</small><p>{item.suggested_phrasing}</p>{links(item.evidence)}
    </article>)}</div>{report.fewer_improvements_reason && <p className="warning">Insufficient evidence: {report.fewer_improvements_reason}</p>}</section>
    <div className="report-columns compact-actions"><Findings title="Outstanding actions" items={report.next_steps} renderEvidence={links} empty="No outstanding actions reported." /><Findings title="Pending questions / confirmations" items={report.open_questions} renderEvidence={links} empty="No unresolved questions reported." /></div>
    <div className="report-support">
      <Findings title="Customer needs" items={report.customer_needs_and_pain_points} empty="No additional needs reported." renderEvidence={links} />
      <section className="question-inventory"><h4>Questions discussed</h4>{report.questions_asked.map((item, i) => {
        const roles = new Set(item.evidence.map(e => e.role));
        return <p key={i}><span className="question-asker">{roles.size === 1 && !roles.has(null) ? `${[...roles][0]} question` : "Questioner uncertain"}</span>{item.text}{links(item.evidence)}</p>;
      })}</section>
      <Findings title="Strengths" items={report.strengths} empty="No additional strengths reported." renderEvidence={links} />
      <h4>Evidence limitations</h4><ul>{report.evidence_limitations.map((item, i) => <li key={i}>{item}</li>)}</ul>
    </div>
  </div>;
}
