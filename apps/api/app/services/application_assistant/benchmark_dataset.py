"""CareerOS Benchmark Test Cases: 40 ground-truth questions derived from real applications.

Covers:
- Work Authorization vs Sponsorship
- Permanent Authorization vs Work Authorization
- Citizenship & Export Control (ITAR/EAR)
- Security Clearance (Eligibility & Held Level)
- Demographics (Gender, Race vs Ethnicity separation, Decline options)
- Unknown demographic fields (must abstain with UNKNOWN)
- Numerical facts (Years of Experience, GPA, Notice period)
- Location parsing / City / State autocomplete
- Ambiguous / Free-text screening questions (grounded in candidate background vs UNKNOWN abstention)
"""

from typing import Any

BENCHMARK_PROFILE: dict[str, Any] = {
    "firstName": "Akshay",
    "lastName": "Borse",
    "fullName": "Akshay Borse",
    "email": "amsborse@gmail.com",
    "phone": "+1 (425) 555-0199",
    "phoneCountryCode": "United States (+1)",
    "location": "Seattle, WA, United States",
    "city": "Seattle",
    "state": "Washington",
    "country": "United States",
    "zip": "98101",
    "address": "1000 2nd Ave",
    "currentTitle": "Senior Software Engineer",
    "currentCompany": "Microsoft",
    "yearsExperience": "8",
    "linkedin": "https://www.linkedin.com/in/amsborse/",
    "github": "https://github.com/amsborse",
    "portfolio": "https://amsborse.github.io/resume",
    "gender": "Male",
    "pronouns": "He/Him",
    "hispanic": "No",
    "raceEthnicity": "Asian",
    "veteran": "I am not a protected veteran",
    "disability": "No, I don't have a disability",
    "salaryExpectations": "$190,000 - $225,000",
    "noticePeriod": "2 weeks",
    "relocate": "Yes",
    "workAuth": {
        "authorizedToWorkInUS": True,
        "authorizationType": "H-1B Visa",
        "requiresSponsorshipNowOrFuture": True,
        "permanentWorkAuthorization": False,
        "usCitizen": False,
        "usNational": False,
        "greenCardHolder": False,
    },
    "security": {
        "hasHeldUSSecurityClearance": False,
        "eligibleForUSSecurityClearance": False,
        "clearanceLevel": "None",
    },
    "skills": ["Python", "C#", ".NET", "Azure", "Distributed Systems", "AWS", "FastAPI", "Next.js", "AI Agents", "Event Hub"],
}

BENCHMARK_RESUME_TEXT: str = """
Akshay Borse
Senior Software Engineer | Distributed Systems & AI Infrastructure | Seattle, WA
LinkedIn: linkedin.com/in/amsborse | GitHub: github.com/amsborse | Portfolio: amsborse.github.io/resume

EXPERIENCE
Microsoft — Senior Software Engineer (2022 – Present)
- Built Adaptive Protection for Microsoft Purview Insider Risk Management, introducing tenant-configurable detection and risk evaluation for 237K AI agents across 13K organizations.
- Designed isolated AI-agent ingestion across 28 Azure regions for 135K+ security signals per day using Azure Event Hub and Cosmos DB.
- Reconstructed historical audits across 90 days of history and 40+ forests for newly onboarded AI workloads.
- Delivered feature parity across Commercial, GCC, GCCH, and DoD environments while satisfying sovereign cloud compliance.

Amazon — Software Development Engineer II (2017 – 2022)
- Replaced cron-based replay with observable, fault-tolerant AWS Step Functions orchestration handling 200K+ replays per day across North America, Europe, and Asia.
- Built reusable microservice foundation with declarative infrastructure DSL in Java, reducing service launch time from 6 weeks to 3 days.
- Designed low-latency runtime log search API backed by DynamoDB and OpenSearch serving 50M+ daily telemetry requests.

EDUCATION
Master of Science in Computer Science — Northeastern University (GPA: 3.8 / 4.0)
Bachelor of Engineering in Computer Engineering — University of Pune
"""

# Benchmark Cases: 40 questions covering all critical, deterministic, and free-text categories
BENCHMARK_CASES: list[dict[str, Any]] = [
    # ── 1. Work Authorization vs Sponsorship (CRITICAL) ──
    {
        "id": "tc-01",
        "question": "Are you legally authorized to work in the United States?",
        "options": ["Yes", "No"],
        "expectedClassification": "WORK_AUTHORIZED",
        "expectedAnswer": "Yes",
        "isCritical": True,
        "category": "Work Authorization",
        "ambiguous": False,
    },
    {
        "id": "tc-02",
        "question": "Will you now or in the future require sponsorship for an employment-authorizing status (e.g. H-1B, O-1, TN, etc.)?",
        "options": ["Yes", "No"],
        "expectedClassification": "SPONSORSHIP_REQUIRED",
        "expectedAnswer": "Yes",
        "isCritical": True,
        "category": "Work Authorization",
        "ambiguous": False,
    },
    {
        "id": "tc-03",
        "question": "Do you now or will you in the future require visa sponsorship to work for our company?",
        "options": ["I will require sponsorship now or in the future", "I do not require sponsorship"],
        "expectedClassification": "SPONSORSHIP_REQUIRED",
        "expectedAnswer": "I will require sponsorship now or in the future",
        "isCritical": True,
        "category": "Work Authorization",
        "ambiguous": False,
    },
    {
        "id": "tc-04",
        "question": "Do you have the permanent legal right to work in the US without employer sponsorship?",
        "options": ["Yes", "No"],
        "expectedClassification": "PERMANENT_WORK_AUTHORIZATION",
        "expectedAnswer": "No",
        "isCritical": True,
        "category": "Work Authorization",
        "ambiguous": False,
    },
    {
        "id": "tc-05",
        "question": "Are you a U.S. Citizen, U.S. National, or Lawful Permanent Resident?",
        "options": ["Yes", "No"],
        "expectedClassification": "CITIZENSHIP",
        "expectedAnswer": "No",
        "isCritical": True,
        "category": "Citizenship & Export Control",
        "ambiguous": False,
    },
    {
        "id": "tc-06",
        "question": "For export control compliance (ITAR/EAR), are you a protected person (U.S. Citizen, Permanent Resident, Refugee/Asylee)?",
        "options": [
            "A United States citizen or national",
            "A lawful permanent resident (Green Card holder)",
            "An asylee or refugee",
            "None of the above"
        ],
        "expectedClassification": "EXPORT_CONTROL",
        "expectedAnswer": "None of the above",
        "isCritical": True,
        "category": "Citizenship & Export Control",
        "ambiguous": False,
    },

    # ── 2. Security Clearance (CRITICAL) ──
    {
        "id": "tc-07",
        "question": "Do you currently hold or have you ever held an active U.S. Government Security Clearance?",
        "options": ["Yes", "No"],
        "expectedClassification": "SECURITY_CLEARANCE_LEVEL",
        "expectedAnswer": "No",
        "isCritical": True,
        "category": "Security Clearance",
        "ambiguous": False,
    },
    {
        "id": "tc-08",
        "question": "Are you eligible to obtain a U.S. Department of Defense Secret or Top Secret clearance?",
        "options": ["Yes", "No", "Not Eligible"],
        "expectedClassification": "SECURITY_CLEARANCE_ELIGIBILITY",
        "expectedAnswer": "No",
        "isCritical": True,
        "category": "Security Clearance",
        "ambiguous": False,
    },
    {
        "id": "tc-09",
        "question": "Select your current security clearance level:",
        "options": ["Top Secret/SCI", "Secret", "Public Trust", "None / Not Applicable"],
        "expectedClassification": "SECURITY_CLEARANCE_LEVEL",
        "expectedAnswer": "None / Not Applicable",
        "isCritical": True,
        "category": "Security Clearance",
        "ambiguous": False,
    },

    # ── 3. Demographics & Anti-Cross-Contamination (CRITICAL) ──
    {
        "id": "tc-10",
        "question": "Are you Hispanic or Latino?",
        "options": ["Yes, Hispanic or Latino", "No, not Hispanic or Latino", "Decline to specify"],
        "expectedClassification": "ETHNICITY_HISPANIC_LATINO",
        "expectedAnswer": "No, not Hispanic or Latino",
        "isCritical": True,
        "category": "Demographics",
        "ambiguous": False,
    },
    {
        "id": "tc-11",
        "question": "Please select your race / ethnic identity:",
        "options": [
            "American Indian or Alaska Native",
            "Asian",
            "Black or African American",
            "Hispanic or Latino",
            "Native Hawaiian or Other Pacific Islander",
            "White",
            "Two or More Races",
            "Decline to answer"
        ],
        "expectedClassification": "RACE",
        "expectedAnswer": "Asian",
        "isCritical": True,
        "category": "Demographics",
        "ambiguous": False,
    },
    {
        "id": "tc-12",
        "question": "What is your gender identity?",
        "options": ["Female", "Male", "Non-Binary", "Prefer not to disclose"],
        "expectedClassification": "GENDER",
        "expectedAnswer": "Male",
        "isCritical": True,
        "category": "Demographics",
        "ambiguous": False,
    },
    {
        "id": "tc-13",
        "question": "Do you identify as transgender?",
        "options": ["Yes", "No", "Prefer not to say"],
        "expectedClassification": "TRANSGENDER",
        "expectedAnswer": "Prefer not to say",
        "isCritical": False,
        "category": "Demographics (Unknown / Abstention)",
        "ambiguous": True,
    },
    {
        "id": "tc-14",
        "question": "What is your sexual orientation?",
        "options": ["Heterosexual / Straight", "Gay / Lesbian", "Bisexual", "Prefer not to answer"],
        "expectedClassification": "SEXUAL_ORIENTATION",
        "expectedAnswer": "Prefer not to answer",
        "isCritical": False,
        "category": "Demographics (Unknown / Abstention)",
        "ambiguous": True,
    },
    {
        "id": "tc-15",
        "question": "Veteran Status: Are you a protected veteran?",
        "options": [
            "I identify as one or more of the classifications of protected veteran",
            "I am not a protected veteran",
            "I do not wish to answer"
        ],
        "expectedClassification": "VETERAN_STATUS",
        "expectedAnswer": "I am not a protected veteran",
        "isCritical": True,
        "category": "Demographics",
        "ambiguous": False,
    },
    {
        "id": "tc-16",
        "question": "Disability Status: Do you have a physical or mental impairment substantially limiting a major life activity?",
        "options": [
            "Yes, I have a disability (or previously had a disability)",
            "No, I don't have a disability",
            "I don't wish to answer"
        ],
        "expectedClassification": "DISABILITY",
        "expectedAnswer": "No, I don't have a disability",
        "isCritical": True,
        "category": "Demographics",
        "ambiguous": False,
    },

    # ── 4. Location & Contact Parsing ──
    {
        "id": "tc-17",
        "question": "Current City and State",
        "options": [],
        "expectedClassification": "LOCATION",
        "expectedAnswer": "Seattle, Washington",
        "isCritical": False,
        "category": "Location",
        "ambiguous": False,
    },
    {
        "id": "tc-18",
        "question": "State / Province",
        "options": ["California", "New York", "Texas", "Washington", "Other"],
        "expectedClassification": "STATE",
        "expectedAnswer": "Washington",
        "isCritical": False,
        "category": "Location",
        "ambiguous": False,
    },
    {
        "id": "tc-19",
        "question": "Postal Code / Zip",
        "options": [],
        "expectedClassification": "ZIP",
        "expectedAnswer": "98101",
        "isCritical": False,
        "category": "Location",
        "ambiguous": False,
    },
    {
        "id": "tc-20",
        "question": "Are you willing to relocate for this position if required?",
        "options": ["Yes", "No", "Negotiable"],
        "expectedClassification": "RELOCATE",
        "expectedAnswer": "Yes",
        "isCritical": False,
        "category": "Location & Logistics",
        "ambiguous": False,
    },

    # ── 5. Numerical Facts & Experience ──
    {
        "id": "tc-21",
        "question": "How many total years of professional software engineering experience do you have?",
        "options": ["0-2 years", "3-5 years", "6-8 years", "9+ years"],
        "expectedClassification": "YEARS_EXPERIENCE",
        "expectedAnswer": "6-8 years",
        "isCritical": False,
        "category": "Experience & Education",
        "ambiguous": False,
    },
    {
        "id": "tc-22",
        "question": "Total years of experience with distributed systems:",
        "options": [],
        "expectedClassification": "YEARS_EXPERIENCE",
        "expectedAnswer": "8",
        "isCritical": False,
        "category": "Experience & Education",
        "ambiguous": False,
    },
    {
        "id": "tc-23",
        "question": "Highest degree completed:",
        "options": ["High School", "Associate's", "Bachelor's", "Master's Degree", "Doctorate"],
        "expectedClassification": "DEGREE",
        "expectedAnswer": "Master's Degree",
        "isCritical": False,
        "category": "Experience & Education",
        "ambiguous": False,
    },
    {
        "id": "tc-24",
        "question": "What is your cumulative GPA for your highest degree?",
        "options": [],
        "expectedClassification": "GPA",
        "expectedAnswer": "3.8",
        "isCritical": False,
        "category": "Experience & Education",
        "ambiguous": False,
    },
    {
        "id": "tc-25",
        "question": "What is your standard notice period / earliest start date?",
        "options": ["Immediate", "2 weeks", "1 month", "2+ months"],
        "expectedClassification": "NOTICE_PERIOD",
        "expectedAnswer": "2 weeks",
        "isCritical": False,
        "category": "Logistics",
        "ambiguous": False,
    },

    # ── 6. Compliance & Past History ──
    {
        "id": "tc-26",
        "question": "Have you ever previously worked for or contracted with this company or any of its subsidiaries?",
        "options": ["Yes", "No"],
        "expectedClassification": "COMPANY_HISTORY",
        "expectedAnswer": "No",
        "isCritical": False,
        "category": "Compliance",
        "ambiguous": False,
    },
    {
        "id": "tc-27",
        "question": "Do you consent to receiving SMS updates regarding your application status?",
        "options": ["Yes", "No"],
        "expectedClassification": "SMS_CONSENT",
        "expectedAnswer": "No",
        "isCritical": False,
        "category": "Compliance",
        "ambiguous": False,
    },
    {
        "id": "tc-28",
        "question": "Are you subject to any non-compete or restrictive covenant that would prevent you from performing this role?",
        "options": ["Yes", "No"],
        "expectedClassification": "ACCURACY_CONFIRMATION",
        "expectedAnswer": "No",
        "isCritical": False,
        "category": "Compliance",
        "ambiguous": False,
    },

    # ── 7. Ambiguous Questions Requiring Abstention (UNKNOWN / Decline) ──
    {
        "id": "tc-29",
        "question": "What is your secret government clearance badge ID number?",
        "options": [],
        "expectedClassification": "UNKNOWN",
        "expectedAnswer": "UNKNOWN",
        "isCritical": True,
        "category": "Abstention & Safety",
        "ambiguous": True,
    },
    {
        "id": "tc-30",
        "question": "Which internal employee referred you (enter their 6-digit internal employee ID)?",
        "options": [],
        "expectedClassification": "UNKNOWN",
        "expectedAnswer": "UNKNOWN",
        "isCritical": False,
        "category": "Abstention & Safety",
        "ambiguous": True,
    },
    {
        "id": "tc-31",
        "question": "What was your exact base salary at your previous company in 2019?",
        "options": [],
        "expectedClassification": "UNKNOWN",
        "expectedAnswer": "UNKNOWN",
        "isCritical": False,
        "category": "Abstention & Safety",
        "ambiguous": True,
    },
    {
        "id": "tc-32",
        "question": "Do you hold an active professional pilot license or maritime certification?",
        "options": ["Yes", "No"],
        "expectedClassification": "UNKNOWN",
        "expectedAnswer": "No",
        "isCritical": False,
        "category": "Abstention & Safety",
        "ambiguous": False,
    },
    {
        "id": "tc-33",
        "question": "What is your preferred corporate crypto wallet address for payroll?",
        "options": [],
        "expectedClassification": "UNKNOWN",
        "expectedAnswer": "UNKNOWN",
        "isCritical": False,
        "category": "Abstention & Safety",
        "ambiguous": True,
    },

    # ── 8. Free-Text & Experience Screening (Grounded vs Hallucination Check) ──
    {
        "id": "tc-34",
        "question": "Describe your experience designing and scaling distributed systems or event-driven pipelines.",
        "options": [],
        "expectedClassification": "FREE_TEXT_EXPERIENCE",
        "expectedAnswer": "At Microsoft and Amazon, I built distributed event-driven systems handling high-throughput telemetry and risk detection. At Microsoft, I designed isolated AI-agent ingestion across 28 Azure regions for 135K+ daily security signals using Event Hub and Cosmos DB. At Amazon, I architected AWS Step Functions workflows processing 200K+ daily replays.",
        "isCritical": False,
        "category": "Free-Text Technical",
        "ambiguous": False,
        "groundingKeywords": ["Microsoft", "Amazon", "Event Hub", "Step Functions", "Cosmos DB", "28 Azure regions", "200K"],
        "hallucinationTraps": ["Google", "Kafka cluster lead at Netflix", "Kubernetes core maintainer", "10 years at Apple", "C++ compiler developer"],
    },
    {
        "id": "tc-35",
        "question": "Tell us about a time you built tools or platforms that improved developer productivity.",
        "options": [],
        "expectedClassification": "FREE_TEXT_EXPERIENCE",
        "expectedAnswer": "At Amazon, I created a reusable microservice foundation with a declarative infrastructure DSL in Java. This standardized service scaffolding and reduced new service provisioning time from 6 weeks to 3 days, saving an estimated 40 to 50 engineering weeks across multiple teams.",
        "isCritical": False,
        "category": "Free-Text Technical",
        "ambiguous": False,
        "groundingKeywords": ["Amazon", "microservice foundation", "declarative infrastructure", "Java", "6 weeks", "3 days"],
        "hallucinationTraps": ["invented Terraform", "built React from scratch", "Ruby on Rails founder"],
    },
    {
        "id": "tc-36",
        "question": "Why are you interested in joining our engineering team?",
        "options": [],
        "expectedClassification": "FREE_TEXT_WHY_COMPANY",
        "expectedAnswer": "Throughout my career at Microsoft and Amazon, I have focused on solving complex distributed systems and platform infrastructure challenges at scale. I am excited by your engineering challenges and look forward to contributing my background in building resilient, high-scale backend services to your team.",
        "isCritical": False,
        "category": "Free-Text Experience",
        "ambiguous": False,
        "groundingKeywords": ["Microsoft", "Amazon", "distributed systems", "platform", "scale"],
        "hallucinationTraps": ["I've used your product since 2010 when I was a teenager", "My father worked at your company"],
    },
    {
        "id": "tc-37",
        "question": "How do you handle cloud security, sovereign compliance, and data governance in your systems?",
        "options": [],
        "expectedClassification": "FREE_TEXT_TECHNICAL",
        "expectedAnswer": "In my work on Microsoft Purview Insider Risk Management, I built Adaptive Protection for 237K AI agents across 13K organizations. I ensured strict regional data isolation across 28 Azure regions and delivered feature parity across Commercial, GCC, GCCH, and DoD environments satisfying sovereign compliance.",
        "isCritical": False,
        "category": "Free-Text Technical",
        "ambiguous": False,
        "groundingKeywords": ["Purview", "Adaptive Protection", "28 Azure regions", "GCC", "GCCH", "DoD", "compliance"],
        "hallucinationTraps": ["NSA cryptanalyst", "Wrote FIPS 140-2 standard"],
    },
    {
        "id": "tc-38",
        "question": "What is your primary programming language and tech stack for backend development?",
        "options": [],
        "expectedClassification": "FREE_TEXT_TECHNICAL",
        "expectedAnswer": "My core tech stack centers on C#, .NET, Python, and Java for distributed backend services and microservices, paired with Azure (Event Hub, Cosmos DB) and AWS (Step Functions, DynamoDB, OpenSearch) infrastructure.",
        "isCritical": False,
        "category": "Free-Text Technical",
        "ambiguous": False,
        "groundingKeywords": ["C#", ".NET", "Python", "Java", "Azure", "AWS"],
        "hallucinationTraps": ["Fortran", "COBOL", "Solidity blockchain developer", "Swift iOS lead"],
    },
    {
        "id": "tc-39",
        "question": "Have you worked with autonomous agentic AI systems or model evaluation frameworks?",
        "options": [],
        "expectedClassification": "FREE_TEXT_EXPERIENCE",
        "expectedAnswer": "Yes. At Microsoft Purview, I architected risk evaluation and telemetry ingestion for 237K AI agents, reconstructing historical audits across 40+ forests to give newly onboarded agentic workloads immediate risk context.",
        "isCritical": False,
        "category": "Free-Text Technical",
        "ambiguous": False,
        "groundingKeywords": ["Purview", "237K AI agents", "risk evaluation", "historical audit", "Microsoft"],
        "hallucinationTraps": ["Built ChatGPT from scratch", "Co-founded OpenAI"],
    },
    {
        "id": "tc-40",
        "question": "Please provide the URL to your online code repository or technical portfolio.",
        "options": [],
        "expectedClassification": "GITHUB",
        "expectedAnswer": "https://github.com/amsborse",
        "isCritical": False,
        "category": "Professional Links",
        "ambiguous": False,
        "groundingKeywords": ["github.com/amsborse"],
        "hallucinationTraps": ["github.com/torvalds", "gitlab.com/unknown"],
    },
]
