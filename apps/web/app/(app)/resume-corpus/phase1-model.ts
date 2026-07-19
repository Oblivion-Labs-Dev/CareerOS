import type { Accomplishment, PhaseOneAccomplishmentData } from "./types";

function unique(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function matches(values: string[], pattern: RegExp): string[] {
  return unique(values.filter((value) => pattern.test(value)));
}

export function emptyPhaseOneData(): PhaseOneAccomplishmentData {
  return {
    context: {
      businessProblem: "",
      technicalProblem: "",
      whyItMattered: "",
      impactedPeople: "",
      constraints: "",
      dependencies: "",
      expectedOutcome: "",
    },
    ownership: {
      role: "",
      responsibilities: "",
      architectureOwnership: "",
      implementationOwnership: "",
      designOwnership: "",
      leadership: "",
      crossTeamWork: "",
      decisionAuthority: "",
      mentoring: "",
      productionOwnership: "",
      personallyBuilt: "",
    },
    engineeringStory: {
      problem: "",
      constraints: "",
      optionsConsidered: "",
      decisionMade: "",
      decisionRationale: "",
      tradeoffs: "",
      implementation: "",
      failureHandling: "",
      outcome: "",
      lessonsLearned: "",
      improveToday: "",
    },
    impact: {
      business: "",
      engineering: "",
      customer: "",
      operational: "",
      developerProductivity: "",
      longTerm: "",
    },
    technologies: {
      languages: [],
      frameworks: [],
      cloud: [],
      databases: [],
      infrastructure: [],
      messaging: [],
      distributedSystems: [],
      ai: [],
      security: [],
      platformEngineering: [],
    },
    notes: {
      engineeringNotes: "",
      productionStories: "",
      promotionNotes: "",
    },
  };
}

export function phaseOneFromAccomplishment(accomplishment: Accomplishment): PhaseOneAccomplishmentData {
  const empty = emptyPhaseOneData();
  const existing = accomplishment.phaseOne;
  const technologies = unique([...(accomplishment.techStack ?? []), ...(accomplishment.technologies ?? [])]);
  const concepts = unique(accomplishment.concepts ?? []);
  const businessImpact = (accomplishment.impact?.business ?? []).join("\n");
  const engineeringImpact = (accomplishment.impact?.engineering ?? []).join("\n");
  const challenges = (accomplishment.challenges ?? []).join("\n");

  const migrated: PhaseOneAccomplishmentData = {
    context: {
      businessProblem: accomplishment.problemContext?.businessContext || accomplishment.problemContext?.what || "",
      technicalProblem: accomplishment.problemContext?.engineeringContext || challenges,
      whyItMattered: accomplishment.problemContext?.why || businessImpact,
      impactedPeople: accomplishment.problemContext?.who || "",
      constraints: challenges,
      dependencies: "",
      expectedOutcome: businessImpact || engineeringImpact,
    },
    ownership: {
      role: accomplishment.roleDetails?.responsibility || "",
      responsibilities: accomplishment.roleDetails?.contributions?.join("\n") || "",
      architectureOwnership: accomplishment.completenessChecklist?.architectureExplained ? accomplishment.roleDetails?.ownership || "" : "",
      implementationOwnership: accomplishment.roleDetails?.ownership || "",
      designOwnership: accomplishment.decisions?.what || "",
      leadership: (accomplishment.leadership ?? []).join("\n"),
      crossTeamWork: accomplishment.crossTeamInfluence || "",
      decisionAuthority: accomplishment.decisions?.what || "",
      mentoring: accomplishment.mentorship || "",
      productionOwnership: accomplishment.completenessChecklist?.operationalOwnershipShown ? accomplishment.roleDetails?.ownership || "" : "",
      personallyBuilt: accomplishment.roleDetails?.ownership || accomplishment.roleDetails?.responsibility || "",
    },
    engineeringStory: {
      problem: accomplishment.problemContext?.engineeringContext || accomplishment.problemContext?.what || "",
      constraints: challenges,
      optionsConsidered: (accomplishment.decisions?.alternatives ?? []).join("\n"),
      decisionMade: accomplishment.decisions?.what || "",
      decisionRationale: accomplishment.decisions?.why || "",
      tradeoffs: accomplishment.decisions?.tradeoffs || "",
      implementation: [accomplishment.systemDesign?.dataFlow, accomplishment.systemDesign?.eventFlow].filter(Boolean).join("\n"),
      failureHandling: accomplishment.decisions?.failureConsiderations || "",
      outcome: [businessImpact, engineeringImpact].filter(Boolean).join("\n"),
      lessonsLearned: "",
      improveToday: accomplishment.roadmap?.top3Improvements?.[0] || "",
    },
    impact: {
      business: businessImpact,
      engineering: engineeringImpact,
      customer: accomplishment.completenessChecklist?.customerImpactShown ? businessImpact : "",
      operational: accomplishment.completenessChecklist?.operationalOwnershipShown ? engineeringImpact : "",
      developerProductivity: accomplishment.completenessChecklist?.devProductivityExplained ? engineeringImpact : "",
      longTerm: "",
    },
    technologies: {
      languages: matches(technologies, /^(c#|c\+\+|java|javascript|typescript|python|go|rust|ruby|kotlin|swift|\.net)$/i),
      frameworks: matches(technologies, /react|next|spring|django|flask|ray|xgboost|sagemaker/i),
      cloud: matches(technologies, /aws|azure|gcp|bedrock|sagemaker|purview|entra|defender|sentinel|cloudwatch/i),
      databases: matches(technologies, /sql|postgres|mysql|cosmos|dynamo|redis|kusto|mongo|database/i),
      infrastructure: matches(technologies, /kubernetes|docker|bicep|terraform|argo|multi-az|ci\/cd/i),
      messaging: matches(technologies, /kafka|event hub|sqs|queue|messag|stream/i),
      distributedSystems: matches(concepts, /distributed|partition|backpressure|idempoten|consistency|reconciliation|control plane|fault/i),
      ai: unique([...matches(technologies, /ai|llm|rag|model|embedding|gpu|bedrock|sagemaker|xgboost/i), ...matches(concepts, /ai|model|inference|evaluation/i)]),
      security: unique([...matches(technologies, /security|purview|entra|defender|sentinel|oauth|auth/i), ...matches(concepts, /security|identity|policy|privacy|compliance/i)]),
      platformEngineering: unique([...matches(technologies, /platform|kubernetes|docker|terraform|bicep|argo/i), ...matches(concepts, /platform|developer|delivery|control plane/i)]),
    },
    notes: {
      engineeringNotes: "",
      productionStories: "",
      promotionNotes: "",
    },
  };

  if (!existing) return migrated;
  return {
    context: { ...migrated.context, ...existing.context },
    ownership: { ...migrated.ownership, ...existing.ownership },
    engineeringStory: { ...migrated.engineeringStory, ...existing.engineeringStory },
    impact: { ...migrated.impact, ...existing.impact },
    technologies: { ...migrated.technologies, ...existing.technologies },
    notes: { ...migrated.notes, ...existing.notes },
  };
}
