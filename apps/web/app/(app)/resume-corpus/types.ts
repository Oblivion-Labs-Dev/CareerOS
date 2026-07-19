export interface ScaleMetric {
  metric: string;
  value: string;
}

export interface EvidenceItem {
  type: "rfc" | "pr" | "doc" | "screenshot" | "dashboard";
  name: string;
  url: string;
}

export interface PhaseOneAccomplishmentData {
  context: {
    businessProblem: string;
    technicalProblem: string;
    whyItMattered: string;
    impactedPeople: string;
    constraints: string;
    dependencies: string;
    expectedOutcome: string;
  };
  ownership: {
    role: string;
    responsibilities: string;
    architectureOwnership: string;
    implementationOwnership: string;
    designOwnership: string;
    leadership: string;
    crossTeamWork: string;
    decisionAuthority: string;
    mentoring: string;
    productionOwnership: string;
    personallyBuilt: string;
  };
  engineeringStory: {
    problem: string;
    constraints: string;
    optionsConsidered: string;
    decisionMade: string;
    decisionRationale: string;
    tradeoffs: string;
    implementation: string;
    failureHandling: string;
    outcome: string;
    lessonsLearned: string;
    improveToday: string;
  };
  impact: {
    business: string;
    engineering: string;
    customer: string;
    operational: string;
    developerProductivity: string;
    longTerm: string;
  };
  technologies: {
    languages: string[];
    frameworks: string[];
    cloud: string[];
    databases: string[];
    infrastructure: string[];
    messaging: string[];
    distributedSystems: string[];
    ai: string[];
    security: string[];
    platformEngineering: string[];
  };
  notes: {
    engineeringNotes: string;
    productionStories: string;
    promotionNotes: string;
  };
}

export interface ReviewerIntelligence {
  company: string;
  team: string;
  project: string;
  timePeriod: string;
  techStack: string[];
  status: "current" | "archived";
  problemContext: {
    what: string;
    why: string;
    who: string;
    businessContext: string;
    engineeringContext: string;
  };
  roleDetails: {
    responsibility: string;
    ownership: string;
    contributions: string[];
  };
  challenges: string[];
  decisions: {
    what: string;
    why: string;
    alternatives: string[];
    tradeoffs: string;
    rejectedApproaches: string[];
    failureConsiderations: string;
  };
  systemDesign: {
    diagramType: "mermaid" | "text" | "image";
    diagramContent: string;
    dataFlow: string;
    eventFlow: string;
  };
  concepts: string[];
  technologies: string[];
  scaleMetrics: ScaleMetric[];
  impact: {
    business: string[];
    engineering: string[];
  };
  leadership: string[];
  
  reviews: {
    manager: {
      roleName: string;
      wouldCare: boolean;
      wouldInterview: boolean;
      whatLiked: string[];
      whatAverage: string[];
      whatMemorable: string[];
      whatIgnore: string[];
      hiringConfidence: number;
      interviewConfidence: number;
      concerns: string[];
      suggestions: string[];
    };
    principal: {
      roleName: string;
      architectureConcerns: string[];
      systemDesignConcerns: string[];
      engineeringDepth: string;
      scalabilityConcerns: string[];
      distributedSystemsConcerns: string[];
      platformConcerns: string[];
      reliabilityConcerns: string[];
      aiInfraConcerns: string[];
      securityConcerns: string[];
      tradeoffConcerns: string[];
      questionsAsked: string[];
      missingTechDetails: string[];
    };
    devil: {
      roleName: string;
      reasonsToReject: string[];
      reasonsInflated: string[];
      reasonsImplementationOnly: string[];
      reasonsLacksOwnership: string[];
      reasonsLacksDepth: string[];
      reasonsGeneric: string[];
      weakWording: string[];
      weakMetrics: string[];
      missingEngineeringSignal: string;
      weakBusinessImpact: string;
      weakArchitectureSignal: string;
      weakLeadershipSignal: string;
      weakOriginality: string;
      overallRoast: string;
    };
    contrarian: {
      roleName: string;
      hiddenAssumptions: string[];
      blindSpots: string[];
      missingContext: string[];
      alternativeInterpretations: string[];
      misunderstandings: string[];
      questionablePoints: string[];
      reducedCredibilityReasons: string[];
    };
    recruiter: {
      roleName: string;
      surviveScan: boolean;
      keywords: string[];
      scannabilityScore: number;
      tooLong: boolean;
      tooTechnical: boolean;
      notTechnicalEnough: boolean;
      confusing: boolean;
      easyToUnderstand: boolean;
      interviewLikelihood: string;
    };
    ats: {
      roleName: string;
      missingKeywords: string[];
      missingTechnologies: string[];
      missingTerminology: string[];
      missing2026Trends: string[];
      weakKeywordDensity: string;
      overusedWording: string[];
      atsScore: number;
      improvements: string[];
    };
    writer: {
      roleName: string;
      weakVerbs: string[];
      repeatedVerbs: string[];
      passiveWording: string[];
      aiSoundingPhrases: string[];
      cliches: string[];
      sentenceFlow: string;
      readability: string;
      bulletLength: string;
      grammarIssues: string[];
      alternativeWording: string[];
    };
    staff: {
      roleName: string;
      demonstratesArchitecture: boolean;
      demonstratesOwnership: boolean;
      demonstratesLeadership: boolean;
      demonstratesInfluence: boolean;
      demonstratesMentorship: boolean;
      demonstratesDesignReviews: boolean;
      demonstratesStandards: boolean;
      demonstratesLongTermThinking: boolean;
      demonstratesPlatformThinking: boolean;
      staffProudOfThis: boolean;
    };
    interview: {
      roleName: string;
      questions: {
        deepDive: string[];
        architecture: string[];
        failure: string[];
        tradeoff: string[];
        scalability: string[];
        behavioral: string[];
        security: string[];
        operational: string[];
      };
      exposureRiskPoints: string[];
      topicsToStudy: string[];
      confidenceLevel: number;
    };
  };

  completenessChecklist: {
    problemExplained: boolean;
    businessProblemExplained: boolean;
    technicalProblemExplained: boolean;
    architectureExplained: boolean;
    tradeoffsExplained: boolean;
    scaleIncluded: boolean;
    metricsIncluded: boolean;
    impactIncluded: boolean;
    leadershipShown: boolean;
    ownershipShown: boolean;
    decisionShown: boolean;
    failureHandlingExplained: boolean;
    performanceExplained: boolean;
    securityExplained: boolean;
    reliabilityExplained: boolean;
    devProductivityExplained: boolean;
    platformThinkingShown: boolean;
    operationalOwnershipShown: boolean;
    customerImpactShown: boolean;
    businessImpactShown: boolean;
    evidenceAttached: boolean;
    interviewStoryAvailable: boolean;
    diagramAvailable: boolean;
    rfcAttached: boolean;
  };
  completenessStatus: "Complete" | "Incomplete" | "Needs information";

  missingQuestions: {
    id: string;
    question: string;
    category: string;
    answer?: string;
  }[];

  resumeEvolution: {
    current: string;
    improved: string;
    top10Percent: string;
    top1Percent: string;
    atsOptimized: string;
    hmFavorite: string;
    principalFavorite: string;
    mostTechnical: string;
    mostBusiness: string;
    mostConcise: string;
    interview: string;
    linkedin: string;
    star: string;
  };

  confidenceScores: {
    truth: number;
    metric: number;
    architecture: number;
    leadership: number;
    businessImpact: number;
    engineeringImpact: number;
    evidence: number;
    resume: number;
    interview: number;
    lowConfidenceExplanation?: string;
  };

  roastResistanceScore: number;
  roastDeductions: {
    points: number;
    reason: string;
    category: string;
  }[];

  roadmap: {
    top3Improvements: string[];
    missingMetrics: string[];
    missingArchitecture: string[];
    missingEngineeringDetails: string[];
    missingBusinessImpact: string[];
    missingLeadershipEvidence: string[];
    missingInterviewStories: string[];
    missingDocumentation: string[];
  };
  evidence?: EvidenceItem[];

  interviewIntelligence?: {
    recruiterPrep: {
      question: string;
      answer: string;
      confidence: number;
      evidence: string;
    }[];
    hmPrep: {
      question: string;
      idealAnswer: string;
      evidence: string;
      followUps: string[];
    }[];
    seniorPrep: {
      question: string;
      answer: string;
      codeReferences: string;
      evidence: string;
    }[];
    staffPrep: {
      question: string;
      idealAnswer: string;
      architectureDiagram: string;
      tradeoffs: string;
      lessonsLearned: string;
    }[];
    principalPrep: {
      question: string;
      expectedAnswer: string;
      diagram: string;
      tradeoffs: string;
      alternatives: string[];
      followUps: string[];
    }[];
    systemDesignPrep: {
      scratchDesign: {
        functionalRequirements: string[];
        nonFunctionalRequirements: string[];
        scaleAssumptions: string;
        capacityEstimation: string;
        apiDesign: string;
        dataModel: string;
        storage: string;
        messaging: string;
        caching: string;
        security: string;
        failureHandling: string;
        monitoring: string;
        deployment: string;
        futureImprovements: string;
      };
      corporateDesigns: {
        google: string;
        meta: string;
        amazon: string;
        microsoft: string;
        openai: string;
      };
    };
    technicalProbing: {
      level: number;
      levelName: string;
      questions: {
        question: string;
        suggestedAnswer: string;
      }[];
    }[];
    failureAnalysis: {
      whatFailed: string;
      whatAlmostFailed: string;
      productionIssue: string;
      hardestBug: string;
      biggestUnknown: string;
      wrongAssumptions: string;
      redesignPlan: string;
      lessonsLearned: string;
      technicalDebt: string;
      neverDoAgain: string;
    };
    arbReview: {
      reviewerRole: string;
      roleTitle: string;
      question: string;
      idealAnswer: string;
      weakAnswer: string;
      commonMistakes: string[];
      evidence: string;
    }[];
    redTeamReview: {
      category: string;
      attackQuestion: string;
      vulnerabilityIdentified: string;
      defenseStrategy: string;
    }[];
    whiteboardExercise: {
      drawInstructions: string;
      componentExplanations: {
        component: string;
        explanation: string;
      }[];
      apiDetails: string;
      storageDecision: string;
      queueStrategy: string;
      cacheStrategy: string;
      deploymentPlan: string;
      monitoringSetup: string;
      scalingPolicy: string;
      failoverStrategy: string;
      securitySpecs: string;
      tradeoffsList: string[];
    };
    storytelling: {
      recruiter30s: string;
      hm2m: string;
      deepDive5m: string;
      archWalkthrough10m: string;
      executiveSummary: string;
      customerImpact: string;
      starBehavioral: string;
      techPresentation: string;
      conferenceTalk: string;
    };
    readinessDashboard: {
      recruiter: number;
      hiringManager: number;
      seniorEngineer: number;
      staffEngineer: number;
      principalEngineer: number;
      systemDesign: number;
      behavioral: number;
      architecture: number;
      production: number;
      leadership: number;
      security: number;
      distributedSystems: number;
      aiInfrastructure: number;
      explanations: { [key: string]: string };
    };
  };
}

export interface Accomplishment extends ReviewerIntelligence {
  id: string;
  phaseOne?: PhaseOneAccomplishmentData;
  crossTeamInfluence?: string;
  mentorship?: string;
  reliabilityDetails?: string;
  securityConsiderations?: string;
  scaleDetails?: string;
  portfolioVersion?: string;
  missingInformation?: string[];
  missingItemMetadata?: Record<string, {
    priority?: "high" | "medium" | "low";
    researchLocation?: string;
    notes?: string;
  }>;
  /** Durable Resume Corpus quality decisions that should survive normalization. */
  qualityStatusOverrides?: Record<string, "missing" | "weak" | "partial" | "strong" | "interview-ready" | "not-applicable" | "needs-verification">;
  metricMetadata?: Record<string, {
    confidence?: "low" | "medium" | "high";
    verification?: "unverified" | "needs-evidence" | "verified";
    source?: string;
    evidenceIds?: string[];
  }>;
  evidenceMetadata?: Record<string, { relatedGapIds?: string[] }>;
  questionMetadata?: Record<string, {
    answerStatus?: "unanswered" | "draft" | "prepared" | "practiced";
    confidence?: number;
    qualityStatus?: "missing" | "weak" | "partial" | "strong" | "interview-ready" | "not-applicable" | "needs-verification";
    evidenceIds?: string[];
    metricIds?: string[];
    followUpQuestions?: string[];
    reviewerFeedback?: string[];
    practiceHistory?: string[];
  }>;
  createdAt?: string;
  updatedAt?: string;
}
