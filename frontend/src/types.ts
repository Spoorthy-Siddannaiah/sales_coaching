export type Role = "salesperson" | "customer" | null;
export type Context = {
    company: string;
    relevant_needs: string;
    previous_interactions: string;
    objective: string;
};
export type Evidence = {
    quote: string;
    role: Role;
};
export type Finding = {
    text: string;
    evidence: Evidence[];
};
export type Dimension = {
    score: number | null;
    reason: string;
    evidence: Evidence[];
};
export type Improvement = {
    suggestion: string;
    why_it_matters: string;
    suggested_phrasing: string;
    evidence: Evidence[];
};
export type Report = {
    mode: "full" | "limited";
    summary: Finding;
    outcome: Finding | null;
    customer_needs_and_pain_points: Finding[];
    questions_asked: Finding[];
    open_questions: Finding[];
    next_steps: Finding[];
    dimensions: Record<string, Dimension>;
    strengths: Finding[];
    improvements: Improvement[];
    fewer_improvements_reason: string | null;
    evidence_limitations: string[];
};
export type Analysis = {
    id: string;
    transcript_version_id: string;
    status: "pending" | "analyzing" | "completed" | "failed";
    customer_context: Context;
    objective: string;
    provider: string | null;
    model: string;
    report: Report | null;
    error_message: string | null;
    created_at: string;
    latency_seconds: number | null;
    provider_metadata: {
        prompt_version?: string;
        validator_version?: string;
        estimated_cost_usd?: number;
        input_tokens?: number;
        output_tokens?: number;
    } | null;
};
export type ConversationSummary = {
    id: string;
    title: string;
    provider: "notion" | "offline_fixture";
    source_id: string;
    created_at: string;
    analysis_status: string;
};
export type Conversation = ConversationSummary & {
    source_url: string | null;
    customer_context: Context | null;
    context_updated_at: string | null;
    transcript: {
        id: string;
        original_text: string;
        warnings: string[];
        imported_at: string;
        turns: {
            start: number;
            end: number;
            role: Exclude<Role, null>;
        }[];
        source_metadata: {
            synthetic?: boolean;
            license?: string;
            record_id?: string;
            content_status?: string;
            meeting_metadata?: {
                recording?: {
                    start_time?: string;
                    end_time?: string;
                };
                status?: string;
            };
        };
    } | null;
    analyses: Analysis[];
};
export type Runtime = {
    provider: string;
    model: string;
    paid_approval_required: boolean;
};
