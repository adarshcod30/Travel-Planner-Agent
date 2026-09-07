/**
 * Types mirroring the planner's graph state and Aegra's Agent Protocol.
 *
 * These are hand-written rather than generated: the server publishes JSON
 * Schema at `/assistants/{id}/schemas`, but the shapes below are the small
 * subset the UI actually renders, and keeping them explicit makes it obvious
 * when the frontend is reading a field the backend does not promise.
 */

export type BudgetLevel = "budget" | "mid-range" | "luxury";
export type ModelTier = "high" | "mid" | "low" | "fallback";
export type HumanDecision = "accept" | "edit" | "response" | "ignore" | "comments";

/** Names a specialist the graph can re-run. */
export type AgentName =
  | "destination"
  | "weather"
  | "attraction"
  | "budget"
  | "hotel"
  | "customs"
  | "packing"
  | "itinerary";

/** One graph, as described by the server's own /versions route. */
export interface VersionMeta {
  graph_id: string;
  assistant_id: string;
  label: string;
  headline: string;
  adds: string;
  agents: string[];
  parallel: boolean;
  orchestrated: boolean;
  human_in_the_loop: boolean;
  live_research: boolean;
  cross_trip_memory: boolean;
  section_review: boolean;
  notes: string;
}

export interface AgentRun {
  agent: string;
  model_id: string;
  tier: ModelTier;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  repairs: number;
  escalated: boolean;
}

export interface AgentError {
  agent: string;
  error_type: string;
  message: string;
}

export interface DestinationChoice {
  city: string;
  country: string;
  reason: string;
}

export interface Review {
  verdict: "approved" | "needs_revision";
  budget_realistic: boolean;
  pacing_reasonable: boolean;
  issues: string[];
  suggestions: string[];
}

export interface BudgetBreakdown {
  hotel: number;
  food: number;
  transport: number;
  activities: number;
  miscellaneous: number;
  total: number;
  currency: string;
}

export interface Hotel {
  name: string;
  tier: string;
  price_per_night: number;
  rating: number;
  note: string;
}

export interface OrchestratorDecision {
  agents_to_rerun: string[];
  reasoning: string;
}

/** The subset of TripState the UI reads back from a thread. */
export interface TripState {
  request?: string | null;
  days?: number | null;
  interests?: string[] | null;
  budget_level?: BudgetLevel | null;
  season?: string | null;
  travelers?: number | null;
  destination?: DestinationChoice | null;
  budget?: BudgetBreakdown | null;
  hotels?: { hotels: Hotel[] } | null;
  review?: Review | null;
  orchestrator_decision?: OrchestratorDecision | null;
  iteration?: number | null;
  human_decision?: HumanDecision | null;
  human_feedback?: string | null;
  section_comments?: SectionComment[] | null;
  revisions?: Revision[] | null;
  research_notes?: string[] | null;
  final_plan?: string | null;
  agent_runs?: AgentRun[];
  errors?: AgentError[];
}

/**
 * One addressable part of a draft.
 *
 * `owner` is what makes a comment routable: a section with an owner names the
 * specialist that will re-run for it, and one without — the reviewer's own
 * audit, the research provenance — can be read but not revised.
 */
export interface PlanSection {
  key: string;
  title: string;
  owner: AgentName | null;
  body: string;
}

/** One remark, pinned to one section. */
export interface SectionComment {
  section: string;
  comment: string;
}

/** One completed round of review, as the graph recorded it. */
export interface Revision {
  iteration: number;
  decision: HumanDecision;
  comments: SectionComment[];
  feedback: string | null;
  agents_rerun: AgentName[];
  at: string;
}

/** The payload v4's review gate sends when it interrupts. */
export interface PlanReviewInterrupt {
  type: "section_review";
  iteration: number;
  sections: PlanSection[];
  /** The same sections joined, for anything that just wants the document. */
  draft: string;
  review: Review | null;
  revisions: Revision[];
  config: {
    allow_accept: boolean;
    allow_comments: boolean;
    allow_edit: boolean;
    allow_respond: boolean;
    allow_ignore: boolean;
    revision_rounds_left: number;
  };
}

export interface ThreadState {
  values: TripState;
  next: string[];
  tasks?: { interrupts?: { value: PlanReviewInterrupt }[] }[];
}

export interface TripRequest {
  request: string;
  days: number;
  interests: string[];
  budget_level: BudgetLevel;
  season: string;
  travelers: number;
}

/** What the planner page tracks while a run is in flight. */
export type RunPhase = "idle" | "running" | "interrupted" | "done" | "error";
