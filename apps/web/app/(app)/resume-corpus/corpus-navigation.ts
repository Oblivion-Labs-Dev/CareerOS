export type CorpusView =
  | "overview"
  | "accomplishments"
  | "builder"
  | "match"
  | "interview"
  | "metrics"
  | "skills"
  | "graph"
  | "evidence"
  | "reviews"
  | "templates"
  | "settings";

export const CORPUS_VIEW_LABELS: Record<CorpusView, string> = {
  overview: "Overview",
  accomplishments: "Accomplishments",
  builder: "Resume Builder",
  match: "Job Match",
  interview: "Interview",
  metrics: "Metrics",
  skills: "Skills",
  graph: "Knowledge Graph",
  evidence: "Evidence",
  reviews: "Review Center",
  templates: "Templates",
  settings: "Settings",
};

export const CORPUS_VIEWS = Object.keys(CORPUS_VIEW_LABELS) as CorpusView[];

export const PHASE_ONE_VIEWS = [
  "overview",
  "accomplishments",
  "metrics",
  "evidence",
  "interview",
  "settings",
] as const satisfies readonly CorpusView[];

export type ComingSoonCategory = "Review intelligence" | "Generators" | "Analytics" | "Practice & platform";

export interface ComingSoonFeature {
  id: string;
  label: string;
  category: ComingSoonCategory;
  description: string;
  why: string;
  stage: string;
}

const COMING_SOON_ROWS = [
  ["reviews", "Reviewer Intelligence", "Review intelligence", "Map reviewer concerns to the exact accomplishment, claim, and evidence that needs attention.", "Turns scattered feedback into a prioritized improvement loop.", "Phase 2 · Review intelligence"],
  ["devils-advocate", "Devil's Advocate", "Review intelligence", "Stress-test claims with skeptical follow-up questions and counterarguments.", "Helps each accomplishment survive detailed interview probing.", "Phase 2 · Review intelligence"],
  ["contrarian-review", "Contrarian Review", "Review intelligence", "Challenge scope, framing, and impact from an intentionally different point of view.", "Surfaces blind spots before a hiring panel does.", "Phase 2 · Review intelligence"],
  ["ats-review", "ATS Review", "Review intelligence", "Evaluate generated resume content for parsing clarity and role-language coverage.", "Improves discoverability while keeping the corpus factual.", "Phase 2 · Review intelligence"],
  ["resume-writer-review", "Resume Writer Review", "Review intelligence", "Review generated bullets for clarity, compression, and outcome-first structure.", "Creates stronger output without bloating the source record.", "Phase 2 · Review intelligence"],
  ["recruiter-review", "Recruiter Review", "Review intelligence", "Preview how quickly a recruiter can understand relevance, scope, and impact.", "Makes the first read faster and more credible.", "Phase 2 · Review intelligence"],
  ["staff-review", "Staff Review", "Review intelligence", "Probe technical breadth, influence, and cross-team leverage at Staff level.", "Identifies missing signals for senior IC roles.", "Phase 2 · Review intelligence"],
  ["principal-review", "Principal Review", "Review intelligence", "Test architecture judgment, strategic scope, and durable organizational impact.", "Shows where Principal-level narratives need deeper proof.", "Phase 2 · Review intelligence"],
  ["architecture-review-board", "Architecture Review Board", "Review intelligence", "Review options, constraints, tradeoffs, failure modes, and decision quality.", "Makes the engineering story defensible beyond implementation detail.", "Phase 2 · Review intelligence"],
  ["security-review", "Security Review", "Review intelligence", "Inspect threat boundaries, access controls, data handling, and risk decisions.", "Prepares credible answers for security-sensitive work.", "Phase 2 · Review intelligence"],
  ["sre-review", "SRE Review", "Review intelligence", "Probe reliability targets, observability, incident response, and operational ownership.", "Connects technical work to production resilience.", "Phase 2 · Review intelligence"],
  ["builder", "Resume Generator", "Generators", "Generate role-specific bullets from selected source accomplishments.", "Keeps every resume grounded in one verified source of truth.", "Phase 3 · Output generators"],
  ["match", "Job Description Matching", "Generators", "Match a role description to the most relevant accomplishments and evidence.", "Focuses applications on fit without duplicating career data.", "Phase 3 · Output generators"],
  ["star-story-generator", "STAR Story Generator", "Generators", "Shape accomplishment facts into situation, task, action, and result stories.", "Creates interview narratives while preserving the canonical source.", "Phase 3 · Output generators"],
  ["behavioral-story-generator", "Behavioral Story Generator", "Generators", "Build stories around leadership, conflict, ambiguity, and growth.", "Makes the corpus reusable across common interview themes.", "Phase 3 · Output generators"],
  ["linkedin-generator", "LinkedIn Generator", "Generators", "Create profile-ready experience summaries from verified accomplishments.", "Keeps public positioning consistent with the resume.", "Phase 3 · Output generators"],
  ["portfolio-generator", "Portfolio Generator", "Generators", "Turn selected accomplishments and safe evidence into portfolio case studies.", "Makes deep work visible without another source of truth.", "Phase 3 · Output generators"],
  ["resume-variant-generator", "Resume Variant Generator", "Generators", "Create targeted resume variants for different roles, levels, and industries.", "Supports tailoring without fragmenting source data.", "Phase 3 · Output generators"],
  ["promotion-packet-generator", "Promotion Packet Generator", "Generators", "Assemble scope, impact, leadership, and evidence into a promotion narrative.", "Reuses verified history for internal career growth.", "Phase 3 · Output generators"],
  ["system-design-generator", "System Design Generator", "Generators", "Derive design prompts and walkthroughs from real engineering decisions.", "Connects practice to systems the user can explain credibly.", "Phase 3 · Output generators"],
  ["architecture-diagram-generator", "Architecture Diagram Generator", "Generators", "Create editable architecture views from the engineering story and evidence.", "Makes complex system context easier to communicate.", "Phase 3 · Output generators"],
  ["templates", "Templates", "Generators", "Provide reusable output structures for resumes, stories, portfolios, and packets.", "Standardizes artifacts without adding source fields.", "Phase 3 · Output generators"],
  ["evidence-intelligence", "Evidence Intelligence", "Analytics", "Assess evidence strength, provenance, coverage, and disclosure safety.", "Makes strong claims easier to verify and safer to use.", "Phase 2 · Corpus intelligence"],
  ["metric-intelligence", "Metric Intelligence", "Analytics", "Analyze metric confidence, units, sourcing, and contradictions.", "Prevents high-risk numbers from reaching output unverified.", "Phase 2 · Corpus intelligence"],
  ["timeline-analytics", "Timeline Analytics", "Analytics", "Show how scope, impact, and technology changed over time.", "Reveals a clearer career progression story.", "Phase 4 · Career analytics"],
  ["career-analytics", "Career Analytics", "Analytics", "Analyze the distribution and strength of accomplishments across a career.", "Highlights underrepresented work and positioning opportunities.", "Phase 4 · Career analytics"],
  ["leadership-analytics", "Leadership Analytics", "Analytics", "Track decision authority, mentoring, influence, and organizational leverage.", "Makes leadership growth visible without one reductive score.", "Phase 4 · Career analytics"],
  ["skills", "Skill Intelligence", "Analytics", "Connect technologies and concepts to demonstrated, evidence-backed use.", "Distinguishes proven experience from keyword lists.", "Phase 2 · Corpus intelligence"],
  ["graph", "Knowledge Graph", "Analytics", "Explore relationships between accomplishments, technologies, metrics, evidence, and roles.", "Makes a complete corpus easier to reuse.", "Phase 4 · Career analytics"],
  ["roast-resistance", "Roast Resistance Score", "Analytics", "Explain how well a claim withstands skeptical technical and impact questions.", "Directs effort toward the weakest defensibility gaps.", "Phase 2 · Review intelligence"],
  ["interview-readiness-dashboard", "Interview Readiness Dashboard", "Analytics", "Summarize answer coverage, evidence, practice, and confidence.", "Makes preparation gaps visible at a glance.", "Phase 4 · Career analytics"],
  ["research-queue-dashboard", "Research Queue Dashboard", "Analytics", "Coordinate missing facts, where to find them, and verification progress.", "Keeps research focused on the highest-value gaps.", "Phase 2 · Corpus intelligence"],
  ["career-health-dashboard", "Career Health Dashboard", "Analytics", "Surface stale records, evidence gaps, and weak corpus coverage.", "Keeps the knowledge base useful over the long term.", "Phase 4 · Career analytics"],
  ["whiteboard-mode", "Whiteboard Mode", "Practice & platform", "Practice explaining architecture on a distraction-free canvas.", "Builds confidence communicating complex systems live.", "Phase 4 · Practice tools"],
  ["mock-interview", "Mock Interview", "Practice & platform", "Run persona-aware interview sessions grounded in selected accomplishments.", "Turns stored knowledge into practiced, adaptable answers.", "Phase 4 · Practice tools"],
  ["flashcards", "Flashcards", "Practice & platform", "Create recall prompts from metrics, decisions, and follow-up questions.", "Supports lightweight repetition before interviews.", "Phase 4 · Practice tools"],
  ["practice-mode", "Practice Mode", "Practice & platform", "Schedule focused answer practice with feedback and progress history.", "Makes preparation consistent rather than last-minute.", "Phase 4 · Practice tools"],
  ["multi-resume-support", "Multi-Resume Support", "Practice & platform", "Manage generated resumes while retaining one accomplishment corpus.", "Supports different searches without duplicating source data.", "Phase 4 · Platform"],
  ["collaboration", "Collaboration", "Practice & platform", "Invite trusted reviewers to comment on selected records and outputs.", "Keeps feedback connected to its source accomplishment.", "Phase 4 · Platform"],
  ["version-comparison", "Version Comparison", "Practice & platform", "Compare accomplishment and output revisions with provenance intact.", "Makes improvement visible while preserving history.", "Phase 4 · Platform"],
  ["ai-coaching", "AI Coaching", "Practice & platform", "Offer focused coaching based on gaps, role goals, and practice history.", "Turns analysis into a manageable next action.", "Phase 4 · Practice tools"],
  ["command-center", "Command Center", "Practice & platform", "Coordinate applications, artifacts, review, and practice from one view.", "Becomes useful after the source corpus is complete.", "Future · Orchestration"],
  ["experimental-lab", "Experimental Lab", "Practice & platform", "Provide a safe home for unfinished corpus experiments and prototypes.", "Keeps Phase 1 focused while leaving room to explore.", "Future · Exploration"],
] as const satisfies readonly [string, string, ComingSoonCategory, string, string, string][];

export type ComingSoonFeatureId = (typeof COMING_SOON_ROWS)[number][0];

export const COMING_SOON_FEATURES: readonly ComingSoonFeature[] = COMING_SOON_ROWS.map(
  ([id, label, category, description, why, stage]) => ({ id, label, category, description, why, stage }),
);

export const ADVANCED_CORPUS_VIEWS = ["builder", "match", "skills", "graph", "reviews", "templates"] as const satisfies readonly CorpusView[];

export function isCorpusView(value: string | null): value is CorpusView {
  return Boolean(value && value in CORPUS_VIEW_LABELS);
}

export function isAdvancedCorpusView(value: CorpusView): value is (typeof ADVANCED_CORPUS_VIEWS)[number] {
  return (ADVANCED_CORPUS_VIEWS as readonly string[]).includes(value);
}

export function isComingSoonFeatureId(value: string | null): value is ComingSoonFeatureId {
  return Boolean(value && COMING_SOON_FEATURES.some((feature) => feature.id === value));
}

export function getComingSoonFeature(id: string | undefined): ComingSoonFeature | undefined {
  return COMING_SOON_FEATURES.find((feature) => feature.id === id);
}
