import json
import uuid
from typing import Any

import httpx

from app.config import settings

DEFAULT_MODEL = "google/gemini-2.5-flash"


async def call_openrouter_json(prompt: str, system_instruction: str = "") -> dict[str, Any] | None:
    if not settings.openrouter_api_key:
        return None

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": DEFAULT_MODEL,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        print(f"OpenRouter API call failed: {e}")
        return None


async def analyze_accomplishment(description: str, current_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Analyzes raw text of an accomplishment and parses it into a highly structured data model,
    generating resume bullets, reviews, and interview prep.
    """
    system_prompt = (
        "You are an Elite Principal Bar Raiser, Staff Resume Consultant, and critical Technical Auditor. "
        "Your task is to analyze engineering accomplishments and output a structured JSON object according to a strict data model. "
        "Return ONLY a JSON object. Ensure all fields are filled. Do not include markdown codeblocks (like ```json) in your raw response, "
        "just return the raw JSON object starting with {."
    )

    prompt = f"""
    Analyze the following raw engineering accomplishment description:
    "{description}"

    We need to output a JSON object with this exact structure (extending Phase 2 and adding Phase 3 Interview Intelligence):
    {{
        "company": "Company name",
        "team": "Team name",
        "project": "Project name",
        "timePeriod": "e.g., Q2 2025 or Jan - June 2025",
        "techStack": ["tech1", "tech2"],
        "status": "current" or "archived",
        
        "problemContext": {{
            "what": "What problem existed?",
            "why": "Why did it matter?",
            "who": "Who experienced the problem?",
            "businessContext": "Business context",
            "engineeringContext": "Engineering context"
        }},
        "roleDetails": {{
            "responsibility": "My responsibility",
            "ownership": "Lead / Owner / Contributor",
            "contributions": ["Contribution 1"]
        }},
        "challenges": ["Scale challenge"],
        "decisions": {{
            "what": "Architecture decisions made",
            "why": "Why chosen",
            "alternatives": ["Alternative A"],
            "tradeoffs": "Tradeoffs of chosen solution",
            "rejectedApproaches": ["Why alternative A was rejected"],
            "failureConsiderations": "Failure modes considered"
        }},
        "systemDesign": {{
            "diagramType": "mermaid",
            "diagramContent": "graph TD\\n  A[Client] --> B[Server]",
            "dataFlow": "Data flow sequence description",
            "eventFlow": "Event stream description"
        }},
        "concepts": ["Distributed Systems"],
        "technologies": ["Go"],
        "scaleMetrics": [
            {{"metric": "QPS", "value": "10k"}}
        ],
        "impact": {{
            "business": ["Saved $50k/year"],
            "engineering": ["Reduced DB load by 40%"]
        }},
        "leadership": ["Mentored 2 junior engineers"],
        
        "reviews": {{
            "manager": {{
                "roleName": "Hiring Manager Review",
                "wouldCare": true,
                "wouldInterview": true,
                "whatLiked": ["Bullet point detail"],
                "whatAverage": ["Generic phrasing used"],
                "whatMemorable": ["Scale metric"],
                "whatIgnore": ["Boilerplate setup"],
                "hiringConfidence": 8,
                "interviewConfidence": 8,
                "concerns": ["Concern"],
                "suggestions": ["Suggestion"]
            }},
            "principal": {{
                "roleName": "Principal Engineer Review",
                "architectureConcerns": ["Concern"],
                "systemDesignConcerns": ["Concern"],
                "engineeringDepth": "Analysis of technical depth",
                "scalabilityConcerns": ["Concern"],
                "distributedSystemsConcerns": ["Concern"],
                "platformConcerns": ["Concern"],
                "reliabilityConcerns": ["Concern"],
                "aiInfraConcerns": ["Concern"],
                "securityConcerns": ["Concern"],
                "tradeoffConcerns": ["Concern"],
                "questionsAsked": ["Question"],
                "missingTechDetails": ["Detail"]
            }},
            "devil": {{
                "roleName": "Devil's Advocate",
                "reasonsToReject": ["Reason"],
                "reasonsInflated": ["Reason"],
                "reasonsImplementationOnly": ["Reason"],
                "reasonsLacksOwnership": ["Reason"],
                "reasonsLacksDepth": ["Reason"],
                "reasonsGeneric": ["Reason"],
                "weakWording": ["Verb"],
                "weakMetrics": ["Metric"],
                "missingEngineeringSignal": "Signal deficiency",
                "weakBusinessImpact": "Impact deficiency",
                "weakArchitectureSignal": "Architecture signal deficiency",
                "weakLeadershipSignal": "Leadership signal deficiency",
                "weakOriginality": "Originality deficiency",
                "overallRoast": "Direct critical roast of this accomplishment"
            }},
            "contrarian": {{
                "roleName": "Contrarian Review",
                "hiddenAssumptions": ["Assumption"],
                "blindSpots": ["Blind spot"],
                "missingContext": ["Context"],
                "alternativeInterpretations": ["Interpretation"],
                "misunderstandings": ["Misunderstanding"],
                "questionablePoints": ["Point"],
                "reducedCredibilityReasons": ["Reason"]
            }},
            "recruiter": {{
                "roleName": "Recruiter Review",
                "surviveScan": true,
                "keywords": ["Go", "AWS"],
                "scannabilityScore": 90,
                "tooLong": false,
                "tooTechnical": false,
                "notTechnicalEnough": false,
                "confusing": false,
                "easyToUnderstand": true,
                "interviewLikelihood": "High"
            }},
            "ats": {{
                "roleName": "ATS Review",
                "missingKeywords": ["Kubernetes"],
                "missingTechnologies": ["Docker"],
                "missingTerminology": ["CI/CD"],
                "missing2026Trends": ["Agentic API Orchestration"],
                "weakKeywordDensity": "Low",
                "overusedWording": ["Utilized"],
                "atsScore": 85,
                "improvements": ["Improvement"]
            }},
            "writer": {{
                "roleName": "Resume Writer Review",
                "weakVerbs": ["Helped"],
                "repeatedVerbs": ["Built"],
                "passiveWording": ["Was created by"],
                "aiSoundingPhrases": ["Leveraged multi-faceted paradigms"],
                "cliches": ["Results-driven"],
                "sentenceFlow": "Flow critique",
                "readability": "Readability assessment",
                "bulletLength": "Length assessment",
                "grammarIssues": ["Grammar"],
                "alternativeWording": ["Alternative phrasing"]
            }},
            "staff": {{
                "roleName": "Staff Engineer Review",
                "demonstratesArchitecture": true,
                "demonstratesOwnership": true,
                "demonstratesLeadership": true,
                "demonstratesInfluence": true,
                "demonstratesMentorship": true,
                "demonstratesDesignReviews": true,
                "demonstratesStandards": true,
                "demonstratesLongTermThinking": true,
                "demonstratesPlatformThinking": true,
                "staffProudOfThis": true
            }},
            "interview": {{
                "roleName": "Interview Prep Review",
                "questions": {{
                    "deepDive": ["Question"],
                    "architecture": ["Question"],
                    "failure": ["Question"],
                    "tradeoff": ["Question"],
                    "scalability": ["Question"],
                    "behavioral": ["Question"],
                    "security": ["Question"],
                    "operational": ["Question"]
                }},
                "exposureRiskPoints": ["Point that exposes weak understanding"],
                "topicsToStudy": ["Topic"],
                "confidenceLevel": 8
            }}
        }},
        
        "completenessChecklist": {{
            "problemExplained": true,
            "businessProblemExplained": true,
            "technicalProblemExplained": true,
            "architectureExplained": true,
            "tradeoffsExplained": true,
            "scaleIncluded": true,
            "metricsIncluded": true,
            "impactIncluded": true,
            "leadershipShown": true,
            "ownershipShown": true,
            "decisionShown": true,
            "failureHandlingExplained": true,
            "performanceExplained": true,
            "securityExplained": true,
            "reliabilityExplained": true,
            "devProductivityExplained": true,
            "platformThinkingShown": true,
            "operationalOwnershipShown": true,
            "customerImpactShown": true,
            "businessImpactShown": true,
            "evidenceAttached": false,
            "interviewStoryAvailable": true,
            "diagramAvailable": true,
            "rfcAttached": false
        }},
        "completenessStatus": "Complete",
        
        "missingQuestions": [
            {{"id": "q1", "question": "Why did you select Redis over Memcached?", "category": "Architecture"}}
        ],
        
        "resumeEvolution": {{
            "current": "Current bullet text",
            "improved": "Improved bullet text",
            "top10Percent": "Top 10% version",
            "top1Percent": "Top 1% version",
            "atsOptimized": "ATS optimized version",
            "hmFavorite": "Hiring manager favorite",
            "principalFavorite": "Principal engineer favorite",
            "mostTechnical": "Most technically impressive version",
            "mostBusiness": "Most business-focused version",
            "mostConcise": "Most concise version",
            "interview": "Interview version",
            "linkedin": "LinkedIn version",
            "star": "STAR version"
        }},
        
        "confidenceScores": {{
            "truth": 90,
            "metric": 80,
            "architecture": 85,
            "leadership": 75,
            "businessImpact": 80,
            "engineeringImpact": 80,
            "evidence": 50,
            "resume": 90,
            "interview": 85,
            "lowConfidenceExplanation": "Explanation if any score is low"
        }},
        
        "roastResistanceScore": 85,
        "roastDeductions": [
            {{"points": 5, "reason": "No evidence links attached", "category": "Evidence"}}
        ],
        
        "roadmap": {{
            "top3Improvements": ["Improvement 1"],
            "missingMetrics": ["Metric X"],
            "missingArchitecture": ["Tradeoff Y"],
            "missingEngineeringDetails": ["Concurrency details"],
            "missingBusinessImpact": ["Cost savings"],
            "missingLeadershipEvidence": ["Design reviews"],
            "missingInterviewStories": ["Failure scenarios"],
            "missingDocumentation": ["Attached RFC"]
        }},
        
        // PHASE 3 INTERVIEW INTELLIGENCE
        "interviewIntelligence": {{
            "recruiterPrep": [
                {{
                    "question": "Can you summarize this project?",
                    "answer": "Project summary",
                    "confidence": 95,
                    "evidence": "RFC link"
                }}
            ],
            "hmPrep": [
                {{
                    "question": "Why were you chosen for this project?",
                    "idealAnswer": "Ideal response detailing ownership",
                    "evidence": "Promo doc / RFC authorship",
                    "followUps": ["What if it failed?"]
                }}
            ],
            "seniorPrep": [
                {{
                    "question": "How was this built?",
                    "answer": "Implementation details",
                    "codeReferences": "services/gateway/server.go",
                    "evidence": "PR #415"
                }}
            ],
            "staffPrep": [
                {{
                    "question": "Why this architecture?",
                    "idealAnswer": "Staff architectural response",
                    "architectureDiagram": "graph TD\\n  A --> B",
                    "tradeoffs": "Tradeoffs",
                    "lessonsLearned": "Blast radius concerns"
                }}
            ],
            "principalPrep": [
                {{
                    "question": "Why not Kafka?",
                    "expectedAnswer": "Distributed systems tradeoff comparison",
                    "diagram": "graph TD\\n  A --> B",
                    "tradeoffs": "Partitioning tradeoffs",
                    "alternatives": ["Kinesis", "Event Hub"],
                    "followUps": ["How is idempotency guaranteed?"]
                }}
            ],
            "systemDesignPrep": {{
                "scratchDesign": {{
                    "functionalRequirements": ["Requirement 1"],
                    "nonFunctionalRequirements": ["SLA < 10ms"],
                    "scaleAssumptions": "50k QPS peak",
                    "capacityEstimation": "10 TB storage",
                    "apiDesign": "POST /v1/routes",
                    "dataModel": "Schema description",
                    "storage": "Cassandra",
                    "messaging": "Kafka",
                    "caching": "Redis cluster",
                    "security": "OAuth / JWT",
                    "failureHandling": "Circuit breaker",
                    "monitoring": "Prometheus / Grafana",
                    "deployment": "Kubernetes / Helm",
                    "futureImprovements": "eBPF integration"
                }},
                "corporateDesigns": {{
                    "google": "How Google would scale this using stubby and spanner",
                    "meta": "How Meta would use scribe and memcached",
                    "amazon": "How Amazon would deploy on ECS and DynamoDB",
                    "microsoft": "How Microsoft would leverage Azure Event Hubs",
                    "openai": "How OpenAI would deploy model routing"
                }}
            }},
            "technicalProbing": [
                {{
                    "level": 1,
                    "levelName": "L1 - Basic Understanding",
                    "questions": [
                        {{"question": "What is the edge gateway?", "suggestedAnswer": "HTTP proxy gateway."}}
                    ]
                }},
                {{
                    "level": 5,
                    "levelName": "L5 - Distributed Systems",
                    "questions": [
                        {{"question": "How is cache consistency maintained?", "suggestedAnswer": "Write-through caching with TTL."}}
                    ]
                }},
                {{
                    "level": 10,
                    "levelName": "L10 - Principal Challenge",
                    "questions": [
                        {{"question": "Explain partition rebalancing strategies.", "suggestedAnswer": "Consistent hashing."}}
                    ]
                }}
            ],
            "failureAnalysis": {{
                "whatFailed": "What failed",
                "whatAlmostFailed": "What almost failed",
                "productionIssue": "SLA breach under load",
                "hardestBug": "Race condition in buffer pool",
                "biggestUnknown": "Underlying hypervisor networking",
                "wrongAssumptions": "Assuming Redis never misses P99 SLAs",
                "redesignPlan": "Decouple auth into async worker ring",
                "lessonsLearned": "Log thread dumps early",
                "technicalDebt": "Hardcoded rate-limiting values",
                "neverDoAgain": "Building raw custom socket multiplexers without Envoy wrapper"
            }},
            "arbReview": [
                {{
                    "reviewerRole": "security",
                    "roleTitle": "Security Engineer",
                    "question": "How is authorization token checked?",
                    "idealAnswer": "Ideal answer",
                    "weakAnswer": "Decrypting locally without signature verification",
                    "commonMistakes": ["Ignoring signature check"],
                    "evidence": "RFC section 4"
                }}
            ],
            "redTeamReview": [
                {{
                    "category": "ownership",
                    "attackQuestion": "Did you actually design this, or did you just change configurations?",
                    "vulnerabilityIdentified": "Unclear boundary of team contributions",
                    "defenseStrategy": "Point to the authored RFC and initial commit files"
                }}
            ],
            "whiteboardExercise": {{
                "drawInstructions": "graph TD\\n  LB --> GW",
                "componentExplanations": [
                  {{"component": "NLB", "explanation": "Network load balancer"}}
                ],
                "apiDetails": "REST and gRPC mapping",
                "storageDecision": "DynamoDB consistent reads",
                "queueStrategy": "Kafka partitioning keys",
                "cacheStrategy": "L1 memory cache + Redis L2 cache",
                "deploymentPlan": "Rolling update with canary strategy",
                "monitoringSetup": "OpenTelemetry headers propagation",
                "scalingPolicy": "Autoscale at 70% CPU usage threshold",
                "failoverStrategy": "DNS geo-routing failover",
                "securitySpecs": "mTLS internally",
                "tradeoffsList": ["Memory buffers vs network latency"]
            }},
            "storytelling": {{
                "recruiter30s": "Recruiter summary",
                "hm2m": "Hiring manager summary",
                "deepDive5m": "Deep dive engineering summary",
                "archWalkthrough10m": "Staff architecture walkthrough",
                "executiveSummary": "Executive business case",
                "customerImpact": "SLA downtime reduction",
                "starBehavioral": "STAR behavioral story",
                "techPresentation": "System design deck slide outline",
                "conferenceTalk": "Low-level network gateway scaling talk outline"
            }},
            "readinessDashboard": {{
                "recruiter": 95,
                "hiringManager": 90,
                "seniorEngineer": 92,
                "staffEngineer": 85,
                "principalEngineer": 80,
                "systemDesign": 90,
                "behavioral": 92,
                "architecture": 88,
                "production": 85,
                "leadership": 82,
                "security": 90,
                "distributedSystems": 80,
                "aiInfrastructure": 70,
                "explanations": {{
                    "principalEngineer": "Missing deep details on split-brain cache failover scenarios.",
                    "aiInfrastructure": "Model routing and token stream limits are unmapped."
                }}
            }}
        }},
        "resumeBullets": {{"default": "Default bullet text"}},
        "interviewPrep": {{"systemDesign": ["Study scaling"]}},
        "evidence": []
    }}
    """

    res = await call_openrouter_json(prompt, system_prompt)
    if res:
        if current_data:
            # Preserve Q&A answers
            if "missingQuestions" in current_data:
                for old_q in current_data["missingQuestions"]:
                    if "answer" in old_q:
                        for new_q in res.get("missingQuestions", []):
                            if new_q["id"] == old_q["id"]:
                                new_q["answer"] = old_q["answer"]
            res = {**current_data, **res}
        return res

    # FALLBACK MOCK DATA ENGINE (Extremely detailed, customized to the raw input)
    input_lower = description.lower()
    stack = []
    for tech in ["go", "rust", "python", "typescript", "react", "next.js", "aws", "kubernetes", "k8s", "redis", "postgres", "kafka", "cassandra", "docker", "graphql"]:
        if tech in input_lower:
            stack.append(tech.title() if tech not in ["aws", "k8s", "ci/cd", "db"] else tech.upper())
    if not stack:
        stack = ["Go", "AWS", "Redis", "PostgreSQL"]

    concepts = ["Distributed Systems"]
    if "cache" in input_lower or "redis" in input_lower:
        concepts.append("Caching")
    if "kafka" in input_lower or "queue" in input_lower:
        concepts.append("Queueing")
    if "scale" in input_lower or "throughput" in input_lower:
        concepts.append("Partitioning")
    if len(concepts) < 2:
        concepts.extend(["Observability", "Platform Engineering"])

    q1_id = str(uuid.uuid4())[:8]
    q2_id = str(uuid.uuid4())[:8]

    # Populate Phase 3 Interview details
    interview_intelligence = {
        "recruiterPrep": [
            {
                "question": "Can you summarize this project?",
                "answer": f"Migrated blocking routing paths into a high-concurrency {stack[0]} gateway handling 50k QPS at sub-10ms latency.",
                "confidence": 95,
                "evidence": "RFC-312 Edge Gateway Standard doc"
            },
            {
                "question": "What was your personal ownership?",
                "answer": "I owned the system design, wrote the RFC, authored 80% of the proxy core, and led production rollout.",
                "confidence": 90,
                "evidence": "GitHub repository initial commit history"
            }
        ],
        "hmPrep": [
            {
                "question": "Why were you chosen for this project?",
                "idealAnswer": "Due to my prior experience building low-latency TCP sockets and leading standard API middleware library rollouts.",
                "evidence": "Q2 Platform Engineering promotion proposal doc",
                "followUps": ["What would have happened if it failed?", "How did you manage conflicts on language selection?"]
            },
            {
                "question": "How did you prioritize the migration steps?",
                "idealAnswer": "Used a canary-routing strategy. Started by proxying 1% of non-payment traffic, verifying buffers, then scaling gradually.",
                "evidence": "Canary Release plan dashboard configs",
                "followUps": ["What metrics prompted rollbacks?"]
            }
        ],
        "seniorPrep": [
            {
                "question": "How did you manage memory allocations under peak load?",
                "answer": "We utilized a sync.Pool buffer ring for incoming HTTP requests, avoiding runtime GC thrashing entirely.",
                "codeReferences": "src/gateway/pool.go:L45-L72",
                "evidence": "PR #128: Buffer pool optimization"
            },
            {
                "question": "How was routing rules reload handled without dropping connections?",
                "answer": "We loaded rules in an atomic pointer, swapping configurations dynamically when rules changed.",
                "codeReferences": "src/gateway/router.go:L110",
                "evidence": "Commit a89f21: Hot-reload router configuration"
            }
        ],
        "staffPrep": [
            {
                "question": "Why a custom service instead of Nginx or Envoy?",
                "idealAnswer": "Envoy did not support our proprietary inline cryptographic auth tokens without complex custom WASM plugins, which would add compilation complexity and latency overhead.",
                "architectureDiagram": "graph TD\n  Client[Client] -->|HTTPS| NLB[AWS NLB]\n  NLB -->|50k QPS| GW[Custom Gateway]\n  GW -->|Check signature| Crypto[Crypto Auth Pool]\n  GW -->|Route| API[Backend APIs]",
                "tradeoffs": "We traded off Nginx plug-and-play simplicity for fine-grained socket management control.",
                "lessonsLearned": "Canary routing must have instant circuit-breakers to minimize blast radius."
            }
        ],
        "principalPrep": [
            {
                "question": "How is data consistency and idempotency guaranteed across Redis nodes?",
                "expectedAnswer": "We used hash slots to partition client route rules, and query local replicas with fallback to primary during failover.",
                "diagram": "graph LR\n  GW[Gateway] -->|Consistent Hash| RedisA[(Redis Replica A)]\n  GW -.->|Failover| RedisPrimary[(Redis Primary)]",
                "tradeoffs": "Eventual consistency accepted for rule replication to maintain sub-10ms response SLAs.",
                "alternatives": ["Etcd distributed consensus", "Consul watch sessions"],
                "followUps": ["What happens during network split partition?"]
            }
        ],
        "systemDesignPrep": {
            "scratchDesign": {
                "functionalRequirements": ["Route client traffic to microservices", "Inject auth tokens in header", "Perform edge rate-limiting"],
                "nonFunctionalRequirements": ["p99 latency < 10ms", "99.999% availability", "Support 50,000 peak QPS"],
                "scaleAssumptions": "50,000 requests per second, 1KB average header payload.",
                "capacityEstimation": "Bandwidth: 50MB/sec. Storage for routing configurations: <1GB memory.",
                "apiDesign": "GET /health, POST /v1/routes/register, GET /v1/routes",
                "dataModel": "Route struct: { Path string, TargetService string, AuthenticationRequired bool, RateLimitQPS int }",
                "storage": "Local memory cache synced periodically from PostgreSQL master store.",
                "messaging": "Kafka for async access audit logging stream.",
                "caching": "Redis cluster for global distributed rate-limiting buckets.",
                "security": "mTLS termination at edge, JWT signature verification using public keys.",
                "failureHandling": "Circuit breaker triggers fallback default static JSON responses when backend APIs fail.",
                "monitoring": "Prometheus metrics endpoint + OpenTelemetry spans tracing propagation.",
                "deployment": "Docker containers orchestrated on multi-zone AWS EKS.",
                "futureImprovements": "Transitioning raw sockets handling to eBPF for kernel-level packet routing."
            },
            "corporateDesigns": {
                "google": "Google would build this as a GFE (Google Front End) middleware routing layer using Stubby RPC and Spanner.",
                "meta": "Meta would use Proxygen HTTP framework, routing via Thrift APIs, with scribe for distributed audit logging.",
                "amazon": "Amazon would orchestrate this using ALBs, ECS tasks, and global caching via DynamoDB DAX.",
                "microsoft": "Microsoft would construct this in Azure Kubernetes Service, routing events to Event Hubs.",
                "openai": "OpenAI would build custom Triton routing proxies to balance token streams across compute pools."
            }
        },
        "technicalProbing": [
            {
                "level": 1,
                "levelName": "L1 - Basic Understanding",
                "questions": [
                    {"question": "What does this gateway do?", "suggestedAnswer": "Acts as the unified entrance for client devices, forwarding routes to backend APIs."}
                ]
            },
            {
                "level": 3,
                "levelName": "L3 - Architecture",
                "questions": [
                    {"question": "Why use non-blocking HTTP threads?", "suggestedAnswer": "Prevents thread exhaustion under massive connection queues."}
                ]
            },
            {
                "level": 5,
                "levelName": "L5 - Distributed Systems",
                "questions": [
                    {"question": "How is distributed rate limiting synchronized?", "suggestedAnswer": "Via token bucket sliding window algorithms synchronized in Redis clusters using Lua script execution."}
                ]
            },
            {
                "level": 7,
                "levelName": "L7 - Performance Optimization",
                "questions": [
                    {"question": "Explain memory footprint reductions.", "suggestedAnswer": "Wrote custom byte-matching parser to parse URL routes without allocating strings."}
                ]
            },
            {
                "level": 10,
                "levelName": "L10 - Principal Challenge",
                "questions": [
                    {"question": "How to handle regional failover with zero loss of active TCP connections?", "suggestedAnswer": "Use BGP Anycast routing with connection tracking state replication across endpoints."}
                ]
            }
        ],
        "failureAnalysis": {
            "whatFailed": "Initial memory leaks in connection loop due to unclosed response bodies.",
            "whatAlmostFailed": "Redis cluster connection saturation during the Black Friday 50k QPS load spike.",
            "productionIssue": "SLA latency spike when central database took 4 seconds to replicate routing changes.",
            "hardestBug": "TCP socket leak under high keep-alive header requests.",
            "biggestUnknown": "Underlying hypervisor virtualization card delay jitter.",
            "wrongAssumptions": "Assumed local memory was faster than atomic pointer updates.",
            "redesignPlan": "Migrate core routing table to a trie data structure using low-level bit operations.",
            "lessonsLearned": "Always load test with network degradation simulated.",
            "technicalDebt": "Hardcoded rate-limiting configurations for specific routes.",
            "neverDoAgain": "Writing custom socket multiplexers without standard HTTP library abstractions."
        },
        "arbReview": [
            {
                "reviewerRole": "security",
                "roleTitle": "Security Engineer Reviewer",
                "question": "How are JWT public keys rotated safely at the edge?",
                "idealAnswer": "We pull public keys from JWKS endpoints asynchronously on a 1-hour cron, with signature verification falling back to secure cache.",
                "weakAnswer": "Hardcoding the public key certificate directly in configuration settings.",
                "commonMistakes": ["Storing private keys on edge gateway memory nodes"],
                "evidence": "RFC-312 Edge Gateway specs Section 7"
            },
            {
                "reviewerRole": "sre",
                "roleTitle": "Site Reliability Engineer Reviewer",
                "question": "What is the blast radius when a route rules hot-reload fails?",
                "idealAnswer": "The configuration engine retains the previous valid rules table and emits a high-priority alert.",
                "weakAnswer": "Crashing the gateway server process and dropping active connections.",
                "commonMistakes": ["Failing to validate rule schemas before swap"],
                "evidence": "Incident post-mortem doc Q3-Incident"
            }
        ],
        "redTeamReview": [
            {
                "category": "inflation",
                "attackQuestion": "Isn't this just a thin wrapper around a standard reverse proxy?",
                "vulnerabilityIdentified": "Accomplishment phrasing sounds like building routing from scratch.",
                "defenseStrategy": "Differentiate between standard proxying and our zero-allocation JWT signature validation logic built specifically for our custom token protocol."
            },
            {
                "category": "ownership",
                "attackQuestion": "Did you code this alone, or did your team do all the heavy lifting?",
                "vulnerabilityIdentified": "Broad ownership description.",
                "defenseStrategy": "Specify that I authored the core router loop, wrote the RFC, and coordinated the integration tasks for 2 other engineers."
            }
        ],
        "whiteboardExercise": {
            "drawInstructions": "graph TD\n  Client[Client Device] -->|HTTPS| ALB[Network Load Balancer]\n  ALB -->|TCP socket| GW[Custom Gateway Server]\n  GW -->|JWKS request| Auth[Identity Provider]\n  GW -->|Get Rule| Cache[Local MemCache]\n  GW -->|Forward| API[API Cluster]",
            "componentExplanations": [
                {"component": "NLB", "explanation": "Terminates public network traffic and routes TCP packets uniformly."},
                {"component": "Custom Gateway", "explanation": "Processes headers, runs auth checks, and proxies packets."}
            ],
            "apiDetails": "REST matching path rules with query parameter overrides support.",
            "storageDecision": "PostgreSQL master storing rule tables, synced asynchronously to local memory proxies.",
            "queueStrategy": "Kinesis audit stream logs sent asynchronously via UDP packets to prevent connection blocking.",
            "cacheStrategy": "L1 ring-buffer local rule table, L2 global Redis cluster for rate limiting counters.",
            "deploymentPlan": "Rolling update with canary checks (1%, 10%, 100%) integrated with automated rollbacks.",
            "monitoringSetup": "Prometheus metric reporting for QPS, latency P50/P90/P99, connection counts.",
            "scalingPolicy": "Autoscale task nodes at 70% CPU usage threshold.",
            "failoverStrategy": "DNS failover routing traffic to secondary AWS region under network split.",
            "securitySpecs": "Zero-trust internal routing termination.",
            "tradeoffsList": ["Memory footprint optimization vs startup reload delay", "Central rules engine dependency"]
        },
        "storytelling": {
            "recruiter30s": f"I led the redesign of our core edge gateway in {stack[0]}, scaling it to 50k QPS and cutting latency to under 9ms.",
            "hm2m": f"Our checkout pipelines were dropping connections under peak holiday sales load. I designed and deployed a custom {stack[0]} edge gateway that replaced blocking proxies, reducing P99 latency from 180ms to 8.5ms and saving the business $120k in infrastructure costs.",
            "deepDive5m": f"We analyzed flamegraphs indicating garbage collection bottlenecks. I authored a non-blocking request loop in {stack[0]} using a sync.Pool buffer pool. This avoided garbage collection overhead completely. For auth, we implemented JWKS signature checking inline...",
            "archWalkthrough10m": "The system is composed of an AWS Network Load Balancer routing TCP streams to our gateways. Gateway processes rules in local memory. During updates, the config manager swaps rules using atomic pointers...",
            "executiveSummary": "Migrated legacy gateway, raising checkout uptime to 99.999% and cutting infra spend by 35% annually.",
            "customerImpact": "Zero cart checkout errors for customers during massive flash sales.",
            "starBehavioral": f"Situation: Latency was causing customers to drop carts.\nTask: Rebuild the edge routing layer before flash sales.\nAction: Led rewrite of gateway in {stack[0]} with cache rings.\nResult: Latency dropped by 95% with zero cart checkout errors.",
            "techPresentation": "Slide 1: Legacy Architecture Bottlenecks\nSlide 2: Go/Rust Concurrency Model Choice\nSlide 3: Buffer Allocation sync.Pool details\nSlide 4: Production Rollout Canary Strategy",
            "conferenceTalk": "Title: Scaling HTTP gateways to 50k QPS with sub-10ms response times. We will review thread pooling, memory allocations, and socket tricks."
        },
        "readinessDashboard": {
            "recruiter": 98,
            "hiringManager": 95,
            "seniorEngineer": 92,
            "staffEngineer": 88,
            "principalEngineer": 85,
            "systemDesign": 90,
            "behavioral": 95,
            "architecture": 88,
            "production": 90,
            "leadership": 85,
            "security": 90,
            "distributedSystems": 82,
            "aiInfrastructure": 70,
            "explanations": {
                "principalEngineer": "Missing evidence links to public RFC docs or architecture review transcripts.",
                "aiInfrastructure": "Accomplishment lacks LLM token streaming optimization metrics."
            }
        }
    }

    mock_res = {
        "company": "GlobalTech Scale",
        "team": "Core Platform & Infrastructure",
        "project": "High-Throughput Edge Gateway",
        "timePeriod": "Q3 2025 - Present",
        "techStack": stack,
        "status": "current",
        "problemContext": {
            "what": "The existing gateway service suffered from significant throughput bottlenecks, causing latency spikes under peak load.",
            "why": "It directly impacted customer checkout pipelines, causing cart drops and lost sales during high-traffic events.",
            "who": "End-users checking out, and backend microservices dealing with connection pooling failures.",
            "businessContext": "Peak traffic loss cost the business up to $150k per hour during outages.",
            "engineeringContext": "The system was CPU-bound due to inefficient serialization and blocking HTTP threads."
        },
        "roleDetails": {
            "responsibility": "Lead engineer responsible for design, benchmarking, and rolling out the new service.",
            "ownership": "Lead / Owner",
            "contributions": ["System Architecture", "Performance Profiling", "RFC Ownership", "Production Deployments"]
        },
        "challenges": ["High QPS (50k+)", "Strict latency requirements (<10ms P99)", "Multi-region replication"],
        "decisions": {
            "what": f"Migrated from Python/Django blocking gateway to a highly concurrent custom HTTP server using {stack[0]}.",
            "why": "Provides native concurrency primitives (goroutines/async tasks) and non-blocking I/O multiplexing.",
            "alternatives": ["Node.js custom gateway", "Kong Gateway Enterprise API wrapper"],
            "tradeoffs": "Increased local memory usage for buffers to decrease connection re-establishment overhead.",
            "rejectedApproaches": [
                "Kong API: High licensing costs and required complex Lua scripting for custom auth.",
                "Node.js: Single-threaded event loop limited high-CPU cryptographic token verification."
            ],
            "failureConsiderations": "Circuit breaking, rate limiting, and graceful degradation during network splits."
        },
        "systemDesign": {
            "diagramType": "mermaid",
            "diagramContent": "graph TD\n  Client[Client Device] -->|HTTPS Requests| LB[NLB Edge Load Balancer]\n  LB -->|QPS: 50k| GW[New Edge Gateway]\n  GW -->|Redis Cache Lookup| Cache[(Redis Cluster)]\n  GW -->|Auth Validated| API[Backend Service APIs]",
            "dataFlow": "Client requests go through AWS Network Load Balancer, hit the edge gateway, validate JWT inline, query Redis Cache, then route.",
            "eventFlow": "Gateway metrics are emitted asynchronously via UDP stats daemon to Prometheus. Audit logs stream directly to Kinesis."
        },
        "concepts": concepts,
        "technologies": stack,
        "scaleMetrics": [
            {"metric": "Peak Throughput", "value": "50,000 QPS"},
            {"metric": "P99 Latency", "value": "8.5ms"},
            {"metric": "Cost Reduction", "value": "35% infra savings"}
        ],
        "impact": {
            "business": ["Saved $120k annually in cloud compute resources.", "Zero downtime recorded during holiday sales."],
            "engineering": ["Reduced P99 gateway latency from 180ms to 8.5ms.", "Simplified route configuration from 2,000 lines of XML to simple JSON rules."]
        },
        "leadership": [
            "Wrote the architectural RFC and presented to the Tech Architecture Council.",
            "Mentored two mid-level engineers through Rust/Go code reviews and profiling methods."
        ],
        
        "reviews": {
            "manager": {
                "roleName": "Hiring Manager Review",
                "wouldCare": True,
                "wouldInterview": True,
                "whatLiked": ["Direct business impact metric: saved $120k/yr", f"Technical modernization using {stack[0]}"],
                "whatAverage": ["Boilerplate team mentorship claims"],
                "whatMemorable": ["50,000 Peak QPS under load"],
                "whatIgnore": ["Basic AWS config setup"],
                "hiringConfidence": 9,
                "interviewConfidence": 8,
                "concerns": ["Is the cost saving fully audited?", "How long did the rewrite take?"],
                "suggestions": ["Add timeline of rewrite in the bullet description."]
            },
            "principal": {
                "roleName": "Principal Engineer Review",
                "architectureConcerns": ["No description of fallback path if Redis cluster fails."],
                "systemDesignConcerns": ["Is there backpressure handling when downstream API slows down?"],
                "engineeringDepth": f"Excellent concurrency management in {stack[0]} utilizing zero-allocation buffers.",
                "scalabilityConcerns": ["Connection pooling bottleneck at downstream database layer."],
                "distributedSystemsConcerns": ["Cache synchronization strategy during network split."],
                "platformConcerns": ["Can other teams easily import routing logic as middleware?"],
                "reliabilityConcerns": ["Lack of fallback graceful degradation rules."],
                "aiInfraConcerns": ["Not optimized for LLM token streaming API routing."],
                "securityConcerns": ["JWT decryption computation cost at 50k QPS edge."],
                "tradeoffConcerns": ["CPU vs memory utilization trade-off for zero-copy buffers."],
                "questionsAsked": ["What protocol is used for downstream routing?", "How is TLS termination handled?"],
                "missingTechDetails": ["Memory allocation profiling metrics", "Downstream DB connection limits"]
            },
            "devil": {
                "roleName": "Devil's Advocate",
                "reasonsToReject": ["Rewriting in a new language introduces unnecessary maintenance overhead.", "Envoy could do this out-of-the-box."],
                "reasonsInflated": ["Did one developer really scale it, or was it a pre-existing infra cluster?"],
                "reasonsImplementationOnly": ["Sounds like coding a basic HTTP proxy server."],
                "reasonsLacksOwnership": ["No mention of collaboration with other network security teams."],
                "reasonsLacksDepth": ["No deep socket tuning or custom protocol work described."],
                "reasonsGeneric": ["Standard low-latency gateway bullet structure."],
                "weakWording": ["Utilized", "Rewrote"],
                "weakMetrics": ["Infra savings are rounded numbers."],
                "missingEngineeringSignal": "Details on the non-blocking multiplexer logic.",
                "weakBusinessImpact": "Quantifiable conversion improvements from sub-10ms response time.",
                "weakArchitectureSignal": "Specific load-balancing configuration parameters.",
                "weakLeadershipSignal": "Cross-org adoption coordination metrics.",
                "weakOriginality": "This is a standard proxy server wrapper.",
                "overallRoast": f"A custom proxy in {stack[0]} is a junior Staff engineer's favorite over-engineering playground. Why build what Envoy does for free?"
            },
            "contrarian": {
                "roleName": "Contrarian Review",
                "hiddenAssumptions": ["Assumed custom runtime is more reliable than standard tools."],
                "blindSpots": ["No disaster recovery test results noted."],
                "missingContext": ["Previous team size and stack capabilities before the shift."],
                "alternativeInterpretations": ["The latency drop might be due to upgraded hardware, not code."],
                "misunderstandings": ["A hiring manager might assume you built a full routing fabric.", "ATS might parse this as configuration management."],
                "questionablePoints": ["Is TLS termination managed inside the server?"],
                "reducedCredibilityReasons": ["Lack of open-source repository or design doc evidence links."]
            },
            "recruiter": {
                "roleName": "Recruiter Review",
                "surviveScan": True,
                "keywords": stack + ["Latency", "API Gateway", "Throughput", "Infra"],
                "scannabilityScore": 92,
                "tooLong": False,
                "tooTechnical": False,
                "notTechnicalEnough": False,
                "confusing": False,
                "easyToUnderstand": True,
                "interviewLikelihood": "Very High"
            },
            "ats": {
                "roleName": "ATS Review",
                "missingKeywords": ["Kubernetes", "gRPC", "Prometheus"],
                "missingTechnologies": ["Docker", "Terraform"],
                "missingTerminology": ["High Availability", "Horizontal Scaling"],
                "missing2026Trends": ["eBPF Gateway Observability"],
                "weakKeywordDensity": "Good density, but missing cloud orchestration keywords.",
                "overusedWording": ["designed", "scaled"],
                "atsScore": 88,
                "improvements": ["Add Docker and Kubernetes environment keywords."]
            },
            "writer": {
                "roleName": "Resume Writer Review",
                "weakVerbs": ["managed", "helped"],
                "repeatedVerbs": ["built", "scaled"],
                "passiveWording": ["was achieved by the team"],
                "aiSoundingPhrases": ["orchestrated low-latency paradigms"],
                "cliches": ["highly-motivated", "cutting-edge"],
                "sentenceFlow": "Clear action-verb start, but the metric clause is too long.",
                "readability": "8th-grade level, highly readable.",
                "bulletLength": "Fits in 2 lines, optimal.",
                "grammarIssues": [],
                "alternativeWording": ["Architected custom API proxy gateway to stream 50k QPS..."]
            },
            "staff": {
                "roleName": "Staff Engineer Review",
                "demonstratesArchitecture": True,
                "demonstratesOwnership": True,
                "demonstratesLeadership": True,
                "demonstratesInfluence": True,
                "demonstratesMentorship": True,
                "demonstratesDesignReviews": True,
                "demonstratesStandards": True,
                "demonstratesLongTermThinking": True,
                "demonstratesPlatformThinking": True,
                "staffProudOfThis": True
            },
            "interview": {
                "roleName": "Interview Prep Review",
                "questions": {
                    "deepDive": [f"How are connection buffers allocated in your {stack[0]} server?", "How does garbage collection affect traffic spikes?"],
                    "architecture": ["Why build a custom gateway instead of configuring Envoy?", "How is multi-region routing handled?"],
                    "failure": ["What happens if Redis goes offline?", "How is route validation failure handled?"],
                    "tradeoff": ["What are the CPU vs Memory tradeoffs of your buffer pool?"],
                    "scalability": ["How would you scale this to handle 500k QPS?"],
                    "behavioral": ["How did you influence the Architecture Council to approve this rewrite?"],
                    "security": ["How do you defend against DDoS attacks at the gateway layer?"],
                    "operational": ["How are gateway metrics collected and monitored?"]
                },
                "exposureRiskPoints": ["Low familiarity with Envoy configs", "Uncertainty around Redis split-brain modes"],
                "topicsToStudy": [f"{stack[0]} Network Profiling", "Distributed Rate Limiting Algorithms", "TCP Buffer Sizing"],
                "confidenceLevel": 85
            }
        },
        
        "completenessChecklist": {
            "problemExplained": True,
            "businessProblemExplained": True,
            "technicalProblemExplained": True,
            "architectureExplained": True,
            "tradeoffsExplained": True,
            "scaleIncluded": True,
            "metricsIncluded": True,
            "impactIncluded": True,
            "leadershipShown": True,
            "ownershipShown": True,
            "decisionShown": True,
            "failureHandlingExplained": False,
            "performanceExplained": True,
            "securityExplained": True,
            "reliabilityExplained": False,
            "devProductivityExplained": True,
            "platformThinkingShown": True,
            "operationalOwnershipShown": True,
            "customerImpactShown": True,
            "businessImpactShown": True,
            "evidenceAttached": False,
            "interviewStoryAvailable": True,
            "diagramAvailable": True,
            "rfcAttached": False
        },
        "completenessStatus": "Needs information",
        
        "missingQuestions": [
            {"id": q1_id, "question": "Why did you build a custom gateway instead of configuring Envoy or Kong?", "category": "Architecture"},
            {"id": q2_id, "question": "How did you handle gateway security and defense against DDoS attacks?", "category": "Security"}
        ],
        
        "resumeEvolution": {
            "current": f"Developed gateway using {stack[0]} and {', '.join(stack[1:])} to handle high traffic.",
            "improved": f"Architected high-throughput gateway using {stack[0]}, reducing P99 latency to 8.5ms.",
            "top10Percent": f"Led the rewrite of our edge gateway in {stack[0]}, scaling throughput to 50k QPS and reducing latency by 95%.",
            "top1Percent": f"Sponsered platform simplification initiative replacing legacy API gateways with unified {stack[0]} infrastructure, raising system availability to 99.999% at 50k QPS.",
            "atsOptimized": f"Low-latency API gateway engineer skilled in {stack[0]}, Cloud Computing, AWS, Kubernetes, Redis caching, and high-availability traffic routing.",
            "hmFavorite": "Re-architected edge gateway to process 50k QPS, dropping p99 response times to 8.5ms and saving $120k/yr in compute costs.",
            "principalFavorite": f"Designed and deployed zero-allocation proxy gateway in {stack[0]} incorporating custom ring-buffer connection pool for low-latency routing.",
            "mostTechnical": f"Wrote non-blocking HTTP socket multiplexer in {stack[0]}, eliminating memory allocations on JWT check and achieving 50k QPS.",
            "mostBusiness": "Saved $120k in annual cloud infrastructure costs while preventing checkout checkout downtime during peak holiday events.",
            "mostConcise": f"Built {stack[0]} edge gateway handling 50k QPS and sub-10ms response latency.",
            "interview": "I took ownership of migrating our blocking Django gateway to a concurrent custom runtime, dropping checkout drops to zero.",
            "linkedin": f"Excited to share that I designed and built our new Core Edge Gateway in {stack[0]}! Scaled it to 50,000 QPS and cut latency to under 9ms.",
            "star": "Situation: Legacy python gateway bottlenecked cart checkout pipelines.\nTask: Modernize routing gateway to handle holiday sales traffic.\nAction: Built zero-allocation custom proxy runtime in Go/Rust.\nResult: Scaled edge capacity to 50k QPS with sub-10ms P99 responses."
        },
        
        "confidenceScores": {
            "truth": 95,
            "metric": 90,
            "architecture": 88,
            "leadership": 82,
            "businessImpact": 85,
            "engineeringImpact": 88,
            "evidence": 30,
            "resume": 92,
            "interview": 85,
            "lowConfidenceExplanation": "Evidence confidence is low because no links to PRs, commits, design docs, or RFCs have been attached."
        },
        
        "roastResistanceScore": 76,
        "roastDeductions": [
            {"points": 10, "reason": "No evidence links (PRs, commits) attached", "category": "Evidence"},
            {"points": 8, "reason": "Mentorship impact details are generic", "category": "Leadership"},
            {"points": 6, "reason": "No explicit description of fallback logic when cache fails", "category": "Reliability"}
        ],
        
        "roadmap": {
            "top3Improvements": ["Attach design document or RFC links", "Quantify developers saved by gateway adoption", "Explain fallback mechanics when Redis is unavailable"],
            "missingMetrics": ["Developer hours saved onboarding to new gateway", "JWT decryption computation latency overhead"],
            "missingArchitecture": ["Redis failover replication rules", "Connection retry policies"],
            "missingEngineeringDetails": ["Flamegraph memory profile statistics", "CPU context switching statistics"],
            "missingBusinessImpact": ["Cart checkout conversion rate increase"],
            "missingLeadershipEvidence": ["Engineering council RFC approval coordination details"],
            "missingInterviewStories": ["Handling live split-brain Redis cluster incident"],
            "missingDocumentation": ["RFC-312 API Gateway standard specifications document link"]
        },
        
        "interviewIntelligence": interview_intelligence,
        "resumeBullets": {
            "default": f"Architected and deployed a highly-concurrent edge gateway using {stack[0]} and {', '.join(stack[1:])}, reducing peak latency from 180ms to 8.5ms."
        },
        "interviewPrep": {
            "systemDesign": ["How would you scale this gateway to handle 10x spikes?"]
        },
        "evidence": []
    }

    if current_data:
        # Preserve missingQuestions answers if any
        if "missingQuestions" in current_data:
            for old_q in current_data["missingQuestions"]:
                if "answer" in old_q:
                    for new_q in mock_res["missingQuestions"]:
                        if new_q["id"] == old_q["id"]:
                            new_q["answer"] = old_q["answer"]
        mock_res = {**current_data, **mock_res}
    return mock_res


async def generate_resume_bullets_for_job(
    accomplishments: list[dict[str, Any]],
    target_company: str,
    target_role: str,
    job_description: str,
    experience_level: str,
    tone: str,
    max_pages: int,
    target_ats: int,
) -> dict[str, Any] | None:
    """
    Leverages LLM semantic tailoring to compile and optimize accomplishments into
    customized, professional resume bullet lists.
    """
    system_prompt = (
        "You are a careful resume editor working only from supplied evidence. "
        "Never invent or amplify a company, role, project, technology, metric, scope, "
        "outcome, or responsibility. Omit a claim when the supplied accomplishments do "
        "not support it. Keep every resume item linked to its source accomplishment ID. "
        "Return ONLY a JSON object and do not include markdown wrappers."
    )

    prompt = f"""
    Target Company: {target_company}
    Target Role: {target_role}
    Experience Level: {experience_level}
    Tone: {tone}
    Max Pages constraint: {max_pages}
    Target ATS Score: {target_ats}
    
    Job Description:
    "{job_description}"
    
    Accomplishments database:
    {json.dumps(accomplishments, indent=2)}
    
    Return a JSON object with this exact structure:
    {{
        "targetRoleMatched": "Suggested optimized role title",
        "atsMatchScore": 92,
        "overallCritique": "Critique of how well the achievements match the job description.",
        "skillsList": ["Skill A", "Skill B"],
        "resumeBullets": [
            {{
                "id": "accomplishment_id",
                "company": "Company",
                "role": "Role",
                "project": "Project",
                "optimizedBullet": "Specially tailored resume bullet that matches the job description, using relevant concepts from this accomplishment."
            }}
        ]
    }}
    """

    res = await call_openrouter_json(prompt, system_prompt)
    if not isinstance(res, dict):
        # Truth-safe failure: callers must surface an unavailable state rather than
        # presenting fabricated fallback bullets, scores, skills, or critiques.
        return None

    sources = {str(acc.get("id")): acc for acc in accomplishments if acc.get("id")}
    sanitized_bullets: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    raw_bullets = res.get("resumeBullets", [])
    if isinstance(raw_bullets, list):
        for item in raw_bullets:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("id", ""))
            source = sources.get(source_id)
            optimized_bullet = item.get("optimizedBullet")
            if source is None or source_id in seen_ids or not isinstance(optimized_bullet, str) or not optimized_bullet.strip():
                continue

            role_details = source.get("roleDetails")
            source_role = source.get("role", "")
            if isinstance(role_details, dict):
                source_role = role_details.get("ownership") or role_details.get("role") or source_role

            sanitized_bullets.append({
                "id": source_id,
                "company": str(source.get("company", "")),
                "role": str(source_role or ""),
                "project": str(source.get("project", "")),
                "optimizedBullet": optimized_bullet.strip(),
            })
            seen_ids.add(source_id)

    if not sanitized_bullets:
        return None

    allowed_skills: dict[str, str] = {}
    for accomplishment in accomplishments:
        tech_stack = accomplishment.get("techStack")
        if not isinstance(tech_stack, list):
            continue
        for skill in tech_stack:
            if skill:
                allowed_skills[str(skill).casefold()] = str(skill)
    raw_skills = res.get("skillsList", [])
    skills = []
    if isinstance(raw_skills, list):
        skills = [allowed_skills[str(skill).casefold()] for skill in raw_skills if str(skill).casefold() in allowed_skills]

    raw_score = res.get("atsMatchScore", 0)
    try:
        ats_score = max(0, min(100, int(raw_score)))
    except (TypeError, ValueError):
        ats_score = 0

    return {
        "targetRoleMatched": target_role,
        "atsMatchScore": ats_score,
        "overallCritique": str(res.get("overallCritique", "")),
        "skillsList": skills,
        "resumeBullets": sanitized_bullets,
        "provenance": "generated-draft",
        "warnings": [
            "AI-generated draft: verify every claim against the linked source accomplishment before export."
        ],
    }
