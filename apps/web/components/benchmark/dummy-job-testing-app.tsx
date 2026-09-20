"use client";

import { getClientApiBaseUrl } from "@/lib/api";
import { useState } from "react";

export type InputComponentType = "radio" | "dropdown" | "checkbox" | "multicheckbox" | "text" | "textarea" | "toggle" | "autocomplete";

export interface FieldVariation {
  label: string;
  question: string;
  componentType: InputComponentType;
  options?: string[];
  placeholder?: string;
  note?: string;
}

export interface FieldVariationGroup {
  category: string;
  fieldId: string;
  expectedGroundTruth: string;
  variations: FieldVariation[];
}

export const FIELD_VARIATION_DATASET: FieldVariationGroup[] = [
  {
    category: "Gender & Demographics",
    fieldId: "gender",
    expectedGroundTruth: "Male",
    variations: [
      {
        label: "Radio Button Group",
        question: "What is your gender identity?",
        componentType: "radio",
        options: ["Male", "Female", "Non-binary", "Decline to self-identify"],
      },
      {
        label: "Dropdown Select (Man vs Male)",
        question: "Gender:",
        componentType: "dropdown",
        options: ["Man", "Woman", "Non-binary", "Prefer not to disclose"],
        note: "Tests 'Man' -> Male normalization",
      },
      {
        label: "Compact Radio Pill Group (Legal Sex)",
        question: "Please select your legal sex:",
        componentType: "radio",
        options: ["M", "F", "Other / Decline"],
        note: "Tests 'M' token mapping",
      },
      {
        label: "Multi-select Identity Options",
        question: "How do you describe your gender identity?",
        componentType: "dropdown",
        options: ["Cisgender Man", "Cisgender Woman", "Transgender Man", "Transgender Woman", "Prefer not to state"],
      },
    ],
  },
  {
    category: "Ethnicity & Race Disambiguation",
    fieldId: "race_ethnicity",
    expectedGroundTruth: "Asian (Not Hispanic/Latino)",
    variations: [
      {
        label: "Yes/No Radio (Hispanic Screening)",
        question: "Are you Hispanic or Latino?",
        componentType: "radio",
        options: ["Yes", "No", "Decline to state"],
        note: "CRITICAL: Must return 'No' (never Asian)",
      },
      {
        label: "Federal EEO-1 Dropdown",
        question: "Please select your race / ethnic background:",
        componentType: "dropdown",
        options: ["Asian", "White", "Black or African American", "Hispanic or Latino", "Two or More Races"],
      },
      {
        label: "Multi-checkbox Race Selection",
        question: "Select all racial identities that apply:",
        componentType: "multicheckbox",
        options: ["Asian", "White", "Black or African American", "Native Hawaiian / Pacific Islander", "American Indian / Alaska Native"],
      },
      {
        label: "Compound EEO-1 Radio",
        question: "Race / Ethnicity (select one):",
        componentType: "radio",
        options: ["Asian (Not Hispanic or Latino)", "Hispanic or Latino", "White (Not Hispanic or Latino)", "I decline to identify"],
      },
    ],
  },
  {
    category: "Location & State Autocomplete",
    fieldId: "location",
    expectedGroundTruth: "Seattle, WA (Washington, United States)",
    variations: [
      {
        label: "Live Autocomplete Search",
        question: "Current City and State of Residence:",
        componentType: "autocomplete",
        options: ["Seattle, WA, USA", "Seattle, Washington", "Auburn, WA, USA", "Auburn, ND, USA", "Washington, DC"],
        placeholder: "Start typing city or zip (e.g. Seattle, WA)...",
        note: "CRITICAL: Never pick North Dakota or Washington DC",
      },
      {
        label: "State Full Name Dropdown",
        question: "State / Province:",
        componentType: "dropdown",
        options: ["Washington", "California", "New York", "Texas", "North Dakota", "District of Columbia"],
      },
      {
        label: "2-Letter State Code Select",
        question: "State Code (2-letter):",
        componentType: "dropdown",
        options: ["WA", "CA", "NY", "TX", "ND", "DC", "FL"],
      },
      {
        label: "Standard Text Input (Zip)",
        question: "Postal Code / Zip Code:",
        componentType: "text",
        placeholder: "e.g. 98101",
      },
    ],
  },
  {
    category: "Work Authorization & Visa Sponsorship",
    fieldId: "work_auth",
    expectedGroundTruth: "Authorized = Yes | Sponsorship Required = Yes | Permanent = No",
    variations: [
      {
        label: "Standard Binary Radio (Work Auth)",
        question: "Are you legally authorized to work in the United States?",
        componentType: "radio",
        options: ["Yes", "No"],
        note: "Candidate has H-1B -> Must be Yes",
      },
      {
        label: "Sponsorship Radio (Now or Future)",
        question: "Will you now or in the future require visa sponsorship for employment?",
        componentType: "radio",
        options: ["Yes", "No"],
        note: "CRITICAL: Must be Yes",
      },
      {
        label: "Permanent Legal Right Trap (Radio)",
        question: "Do you have the permanent legal right to work in the US without employer sponsorship?",
        componentType: "radio",
        options: ["Yes", "No"],
        note: "CRITICAL: Must be No (H-1B is temporary)",
      },
      {
        label: "Workday Status Dropdown",
        question: "What is your current US work authorization status?",
        componentType: "dropdown",
        options: ["US Citizen / Green Card", "Temporary Visa (H-1B, L-1, O-1)", "Student (F-1 OPT/CPT)", "Require Sponsorship"],
      },
      {
        label: "Single Confirmation Checkbox",
        question: "I confirm that I will require employer visa sponsorship now or in the future to work in the US.",
        componentType: "checkbox",
        options: ["I confirm"],
      },
    ],
  },
  {
    category: "Citizenship & Export Control (ITAR)",
    fieldId: "citizenship_itar",
    expectedGroundTruth: "US Citizen = No | ITAR Protected Person = No",
    variations: [
      {
        label: "Citizenship Binary Radio",
        question: "Are you a U.S. Citizen or U.S. Permanent Resident?",
        componentType: "radio",
        options: ["Yes", "No"],
        note: "Must be No",
      },
      {
        label: "ITAR Compliance Dropdown",
        question: "For export control compliance (ITAR/EAR), are you a U.S. Person (Citizen, Green Card, Refugee/Asylee)?",
        componentType: "dropdown",
        options: ["Yes, I am a US Person", "No, I am not a US Person", "Decline to answer"],
        note: "CRITICAL: Must be No",
      },
      {
        label: "ITAR Radio Classification",
        question: "Export Compliance Classification:",
        componentType: "radio",
        options: ["US Citizen", "Lawful Permanent Resident", "Non-US Person / Foreign National"],
      },
    ],
  },
  {
    category: "Security Clearance",
    fieldId: "security_clearance",
    expectedGroundTruth: "Clearance Held = No | Clearance Eligible = No",
    variations: [
      {
        label: "Active Clearance Radio",
        question: "Do you currently hold or have you ever held an active U.S. Government Security Clearance?",
        componentType: "radio",
        options: ["Yes", "No"],
        note: "Must be No",
      },
      {
        label: "Clearance Level Dropdown",
        question: "Select your current security clearance level:",
        componentType: "dropdown",
        options: ["None", "Secret", "Top Secret", "TS/SCI", "Confidential"],
      },
      {
        label: "Eligibility Trap (Radio)",
        question: "Are you eligible to obtain a U.S. Department of Defense security clearance (requires US Citizenship)?",
        componentType: "radio",
        options: ["Yes", "No"],
        note: "CRITICAL: Must be No (candidate is on H-1B)",
      },
    ],
  },
  {
    category: "Demographic Decline & Protected Status",
    fieldId: "veteran_disability",
    expectedGroundTruth: "Veteran = Not Protected | Disability = No",
    variations: [
      {
        label: "Veteran Status Radio Group",
        question: "Veteran Status:",
        componentType: "radio",
        options: ["I am not a protected veteran", "I identify as one or more classifications of protected veteran", "I do not wish to self-identify"],
      },
      {
        label: "Disability Form CC-305 Radio",
        question: "Voluntary Self-Identification of Disability:",
        componentType: "radio",
        options: ["YES, I HAVE A DISABILITY", "NO, I DO NOT HAVE A DISABILITY", "I DO NOT WISH TO ANSWER"],
      },
      {
        label: "Transgender Status Dropdown",
        question: "Do you identify as transgender?",
        componentType: "dropdown",
        options: ["Yes", "No", "Decline to self-identify"],
      },
      {
        label: "Sexual Orientation Dropdown",
        question: "What is your sexual orientation?",
        componentType: "dropdown",
        options: ["Heterosexual / Straight", "Gay / Lesbian", "Bisexual", "Prefer not to disclose"],
      },
    ],
  },
  {
    category: "Experience & Numerical Calculations",
    fieldId: "experience_math",
    expectedGroundTruth: "8 Years Total | Distributed Systems = 8 Years | Notice = 2 Weeks",
    variations: [
      {
        label: "Experience Range Radio",
        question: "How many total years of professional software engineering experience do you have?",
        componentType: "radio",
        options: ["1-3 years", "3-5 years", "5-8 years", "8+ years", "10+ years"],
      },
      {
        label: "Distributed Systems Dropdown",
        question: "Years of experience with distributed systems & cloud architecture (Azure/AWS):",
        componentType: "dropdown",
        options: ["0-2 years", "3-5 years", "6-8 years", "9+ years"],
      },
      {
        label: "Notice Period Radio",
        question: "What is your standard notice period / earliest start date?",
        componentType: "radio",
        options: ["Immediately", "2 weeks", "1 month", "More than 1 month"],
      },
      {
        label: "Degree Level Dropdown",
        question: "Highest level of education completed:",
        componentType: "dropdown",
        options: ["High School", "Bachelor's Degree", "Master's Degree", "Doctorate / Ph.D."],
      },
      {
        label: "Numeric Input (GPA)",
        question: "Cumulative GPA for highest degree:",
        componentType: "text",
        placeholder: "e.g. 3.8",
      },
    ],
  },
  {
    category: "Abstention Traps (Must Abstain / UNKNOWN)",
    fieldId: "abstention_traps",
    expectedGroundTruth: "UNKNOWN / Abstain (Zero Hallucinations Allowed)",
    variations: [
      {
        label: "Secret Clearance Badge ID (Text)",
        question: "What is your secret government clearance badge ID number (enter N/A if none):",
        componentType: "text",
        placeholder: "Badge ID #...",
        note: "CRITICAL: Must abstain or write N/A",
      },
      {
        label: "Internal Referral ID (Text)",
        question: "Which internal employee referred you (enter their Employee ID):",
        componentType: "text",
        placeholder: "Employee ID...",
        note: "Must abstain / UNKNOWN",
      },
      {
        label: "Prior Base Salary (Text)",
        question: "What was your exact base salary at your previous company?",
        componentType: "text",
        placeholder: "$...",
        note: "Must decline / leave blank",
      },
      {
        label: "Pilot License Radio",
        question: "Do you hold an active FAA Commercial Pilot License?",
        componentType: "radio",
        options: ["Yes", "No", "N/A"],
        note: "Must be No / N/A",
      },
      {
        label: "Crypto Payroll Wallet (Text)",
        question: "What is your preferred corporate crypto payroll wallet address (ETH/BTC)?",
        componentType: "text",
        placeholder: "0x...",
        note: "Must abstain / UNKNOWN",
      },
    ],
  },
  {
    category: "Open-Ended Free-Text Screening (Resume Grounded)",
    fieldId: "open_ended",
    expectedGroundTruth: "LLM Synthesized text grounded in Microsoft / Amazon background",
    variations: [
      {
        label: "Distributed Systems Textarea",
        question: "Describe your experience designing and scaling high-throughput distributed systems in production.",
        componentType: "textarea",
        placeholder: "Describe architecture, throughput, reliability...",
      },
      {
        label: "Why This Company? Textarea",
        question: "Why are you interested in joining our engineering team?",
        componentType: "textarea",
        placeholder: "Explain your motivation and interest in the company...",
      },
      {
        label: "Agentic AI Textarea",
        question: "Have you worked with autonomous agentic AI systems, LLM tool calling, or multi-agent orchestration?",
        componentType: "textarea",
        placeholder: "Detail your AI agent architecture...",
      },
      {
        label: "Code Repo URL Text",
        question: "Please provide the URL to your online code repository or portfolio:",
        componentType: "text",
        placeholder: "https://github.com/...",
      },
    ],
  },
];

export function DummyJobTestingApp() {
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [testResults, setTestResults] = useState<Record<string, any>>({});
  const [loadingMap, setLoadingMap] = useState<Record<string, boolean>>({});
  const [activeModel, setActiveModel] = useState<string>("qwen2.5:3b");
  const [batchRunning, setBatchRunning] = useState<boolean>(false);
  const [userInputs, setUserInputs] = useState<Record<string, any>>({});

    // Same-origin through the Next proxy, so the login session cookie travels
  // with the request. Resolved at call time, not module scope: at module
  // scope this evaluates during SSR, where it would freeze to the server-side
  // origin and defeat the point.
    const apiUrl = getClientApiBaseUrl();

  const handleTestField = async (caseKey: string, question: string, options: string[] = [], fieldId: string) => {
    try {
      setLoadingMap((prev) => ({ ...prev, [caseKey]: true }));
      const res = await fetch(`${apiUrl}/benchmarks/test-resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          options,
          fieldId,
          model: activeModel,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setTestResults((prev) => ({ ...prev, [caseKey]: data }));
        // Automatically autofill the interactive UI component with the resolved answer
        if (data.resolvedAnswer) {
          setUserInputs((prev) => ({ ...prev, [caseKey]: data.resolvedAnswer }));
        }
      }
    } catch (e) {
      console.error("Failed to test resolve", e);
    } finally {
      setLoadingMap((prev) => ({ ...prev, [caseKey]: false }));
    }
  };

  const handleRunAllInView = async () => {
    setBatchRunning(true);
    for (const group of FIELD_VARIATION_DATASET) {
      if (selectedCategory !== "all" && group.category !== selectedCategory) continue;
      for (let i = 0; i < group.variations.length; i++) {
        const v = group.variations[i];
        const key = `${group.fieldId}_${i}`;
        await handleTestField(key, v.question, v.options || [], group.fieldId);
      }
    }
    setBatchRunning(false);
  };

  const renderInteractiveComponent = (variation: FieldVariation, caseKey: string) => {
    const value = userInputs[caseKey] || "";
    const options = variation.options || [];

    switch (variation.componentType) {
      case "radio":
        return (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", margin: "0.6rem 0" }}>
            {options.map((opt) => {
              const isChecked = value.toLowerCase().includes(opt.toLowerCase()) || opt.toLowerCase().includes(value.toLowerCase());
              return (
                <label
                  key={opt}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    fontSize: "0.82rem",
                    color: isChecked ? "#38bdf8" : "#cbd5e1",
                    background: isChecked ? "rgba(56, 189, 248, 0.1)" : "rgba(0,0,0,0.2)",
                    padding: "0.35rem 0.6rem",
                    borderRadius: "6px",
                    border: isChecked ? "1px solid rgba(56, 189, 248, 0.4)" : "1px solid rgba(255,255,255,0.04)",
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="radio"
                    name={caseKey}
                    value={opt}
                    checked={isChecked}
                    onChange={() => setUserInputs((prev) => ({ ...prev, [caseKey]: opt }))}
                    style={{ accentColor: "#38bdf8" }}
                  />
                  <span>{opt}</span>
                </label>
              );
            })}
          </div>
        );

      case "dropdown":
        return (
          <div style={{ margin: "0.6rem 0" }}>
            <select
              value={value}
              onChange={(e) => setUserInputs((prev) => ({ ...prev, [caseKey]: e.target.value }))}
              style={{
                width: "100%",
                padding: "0.5rem 0.75rem",
                background: "#0f172a",
                color: value ? "#38bdf8" : "#94a3b8",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: "6px",
                fontSize: "0.82rem",
                outline: "none",
                fontWeight: value ? 600 : 400,
              }}
            >
              <option value="" disabled>-- Select an option --</option>
              {options.map((opt) => (
                <option key={opt} value={opt} style={{ background: "#0f172a", color: "#fff" }}>
                  {opt}
                </option>
              ))}
            </select>
          </div>
        );

      case "multicheckbox":
        return (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", margin: "0.6rem 0" }}>
            {options.map((opt) => {
              const isChecked = value.includes(opt);
              return (
                <label
                  key={opt}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    fontSize: "0.82rem",
                    color: isChecked ? "#10b981" : "#cbd5e1",
                    background: isChecked ? "rgba(16, 185, 129, 0.1)" : "rgba(0,0,0,0.2)",
                    padding: "0.35rem 0.6rem",
                    borderRadius: "6px",
                    border: isChecked ? "1px solid rgba(16, 185, 129, 0.4)" : "1px solid rgba(255,255,255,0.04)",
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={(e) => {
                      const current = Array.isArray(value) ? value : value ? [value] : [];
                      const next = e.target.checked ? [...current, opt] : current.filter((item: string) => item !== opt);
                      setUserInputs((prev) => ({ ...prev, [caseKey]: next }));
                    }}
                    style={{ accentColor: "#10b981" }}
                  />
                  <span>{opt}</span>
                </label>
              );
            })}
          </div>
        );

      case "checkbox":
        return (
          <div style={{ margin: "0.6rem 0" }}>
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.6rem",
                fontSize: "0.82rem",
                color: value ? "#10b981" : "#cbd5e1",
                background: value ? "rgba(16, 185, 129, 0.1)" : "rgba(0,0,0,0.2)",
                padding: "0.5rem 0.75rem",
                borderRadius: "6px",
                border: value ? "1px solid rgba(16, 185, 129, 0.4)" : "1px solid rgba(255,255,255,0.04)",
                cursor: "pointer",
              }}
            >
              <input
                type="checkbox"
                checked={Boolean(value)}
                onChange={(e) => setUserInputs((prev) => ({ ...prev, [caseKey]: e.target.checked ? "Yes" : "" }))}
                style={{ accentColor: "#10b981" }}
              />
              <span>{options[0] || "I agree and confirm"}</span>
            </label>
          </div>
        );

      case "autocomplete":
        return (
          <div style={{ margin: "0.6rem 0" }}>
            <input
              type="text"
              value={value}
              onChange={(e) => setUserInputs((prev) => ({ ...prev, [caseKey]: e.target.value }))}
              placeholder={variation.placeholder || "Type to search..."}
              style={{
                width: "100%",
                padding: "0.5rem 0.75rem",
                background: "#0f172a",
                color: "#38bdf8",
                border: "1px solid rgba(56, 189, 248, 0.3)",
                borderRadius: "6px",
                fontSize: "0.82rem",
                outline: "none",
                fontWeight: 600,
              }}
            />
            {options.length > 0 && (
              <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", marginTop: "0.4rem" }}>
                {options.map((opt) => (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => setUserInputs((prev) => ({ ...prev, [caseKey]: opt }))}
                    style={{
                      fontSize: "0.68rem",
                      background: value === opt ? "#6366f1" : "rgba(255,255,255,0.06)",
                      color: value === opt ? "#fff" : "#94a3b8",
                      border: "none",
                      padding: "2px 6px",
                      borderRadius: "4px",
                      cursor: "pointer",
                    }}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}
          </div>
        );

      case "textarea":
        return (
          <div style={{ margin: "0.6rem 0" }}>
            <textarea
              rows={3}
              value={value}
              onChange={(e) => setUserInputs((prev) => ({ ...prev, [caseKey]: e.target.value }))}
              placeholder={variation.placeholder || "Enter details..."}
              style={{
                width: "100%",
                padding: "0.5rem 0.75rem",
                background: "#0f172a",
                color: "#e2e8f0",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: "6px",
                fontSize: "0.8rem",
                outline: "none",
                lineHeight: "1.4",
              }}
            />
          </div>
        );

      case "text":
      default:
        return (
          <div style={{ margin: "0.6rem 0" }}>
            <input
              type="text"
              value={value}
              onChange={(e) => setUserInputs((prev) => ({ ...prev, [caseKey]: e.target.value }))}
              placeholder={variation.placeholder || "Enter value..."}
              style={{
                width: "100%",
                padding: "0.5rem 0.75rem",
                background: "#0f172a",
                color: value ? "#38bdf8" : "#94a3b8",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: "6px",
                fontSize: "0.82rem",
                outline: "none",
              }}
            />
          </div>
        );
    }
  };

  const categories = ["all", ...FIELD_VARIATION_DATASET.map((g) => g.category)];

  return (
    <div style={{ maxWidth: "1400px", margin: "0 auto", padding: "1.5rem" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.4rem" }}>
            <span style={{ fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#10b981", fontWeight: 700, background: "rgba(16, 185, 129, 0.1)", padding: "2px 8px", borderRadius: "6px" }}>
              🧪 QA Sandbox & Component Stress Test
            </span>
          </div>
          <h1 style={{ fontSize: "2rem", fontWeight: 800, margin: 0, color: "#f8fafc" }}>
            Dummy Job Application Test Bed
          </h1>
          <p style={{ color: "#94a3b8", fontSize: "0.95rem", margin: "0.4rem 0 0", maxWidth: "850px" }}>
            Interactive testing sandbox with <strong>Radio Groups, Multi-Checkboxes, Searchable Autocompletes, Textareas, and Dropdown Selects</strong> across 40+ high-risk variations to inspect exact AI agent returns and DOM verification.
          </p>
        </div>

        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <div style={{ background: "rgba(30, 41, 59, 0.7)", border: "1px solid rgba(255, 255, 255, 0.1)", borderRadius: "8px", padding: "0.4rem 0.8rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ fontSize: "0.8rem", color: "#94a3b8" }}>Resolver Model:</span>
            <select
              value={activeModel}
              onChange={(e) => setActiveModel(e.target.value)}
              style={{ background: "transparent", color: "#f8fafc", border: "none", outline: "none", fontWeight: 600, cursor: "pointer" }}
            >
              <option value="qwen2.5:3b" style={{ background: "#0f172a" }}>qwen2.5:3b (Fast)</option>
              <option value="gemma3:12b" style={{ background: "#0f172a" }}>gemma3:12b (Recommended)</option>
              <option value="mistral-small3.2:24b" style={{ background: "#0f172a" }}>mistral-small3.2:24b (Top Acc)</option>
              <option value="gemini-3.6-flash" style={{ background: "#0f172a" }}>gemini-3.6-flash (Cloud)</option>
            </select>
          </div>

          <button
            onClick={handleRunAllInView}
            disabled={batchRunning}
            style={{
              padding: "0.6rem 1.2rem",
              background: batchRunning ? "#475569" : "linear-gradient(135deg, #10b981 0%, #059669 100%)",
              color: "#fff",
              border: "none",
              borderRadius: "8px",
              fontWeight: 700,
              cursor: batchRunning ? "not-allowed" : "pointer",
              boxShadow: "0 4px 12px rgba(16, 185, 129, 0.3)",
            }}
          >
            {batchRunning ? "⚡ Autofilling All Fields…" : "⚡ Autofill All Visible Fields"}
          </button>
        </div>
      </div>

      {/* Category Filter Pills */}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "1.5rem" }}>
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setSelectedCategory(cat)}
            style={{
              padding: "0.4rem 0.9rem",
              borderRadius: "8px",
              fontSize: "0.8rem",
              fontWeight: 600,
              background: selectedCategory === cat ? "#6366f1" : "rgba(30, 41, 59, 0.6)",
              color: selectedCategory === cat ? "#fff" : "#94a3b8",
              border: selectedCategory === cat ? "1px solid #818cf8" : "1px solid rgba(255,255,255,0.06)",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            {cat === "all" ? "🌐 All 40+ Field Variations" : cat}
          </button>
        ))}
      </div>

      {/* Field Variation Groups */}
      <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
        {FIELD_VARIATION_DATASET.filter((g) => selectedCategory === "all" || g.category === selectedCategory).map((group) => (
          <div
            key={group.category}
            style={{
              background: "rgba(15, 23, 42, 0.8)",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              borderRadius: "14px",
              padding: "1.25rem",
              boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", borderBottom: "1px solid rgba(255,255,255,0.06)", paddingBottom: "0.75rem" }}>
              <div>
                <h3 style={{ fontSize: "1.1rem", fontWeight: 700, margin: 0, color: "#f8fafc", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  📁 {group.category}
                </h3>
                <span style={{ fontSize: "0.8rem", color: "#94a3b8" }}>
                  Expected Truth: <strong style={{ color: "#10b981" }}>{group.expectedGroundTruth}</strong>
                </span>
              </div>
              <span style={{ fontSize: "0.75rem", color: "#64748b", background: "rgba(0,0,0,0.3)", padding: "2px 8px", borderRadius: "6px" }}>
                {group.variations.length} test variations
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "1rem" }}>
              {group.variations.map((variation, idx) => {
                const caseKey = `${group.fieldId}_${idx}`;
                const result = testResults[caseKey];
                const isLoading = loadingMap[caseKey];

                return (
                  <div
                    key={idx}
                    style={{
                      background: "rgba(30, 41, 59, 0.4)",
                      border: `1px solid ${result ? (result.canAutoSubmit ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)") : "rgba(255, 255, 255, 0.05)"}`,
                      borderRadius: "10px",
                      padding: "1rem",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "space-between",
                    }}
                  >
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                          <span style={{ fontSize: "0.7rem", padding: "1px 6px", borderRadius: "4px", background: "rgba(99, 102, 241, 0.2)", color: "#818cf8", fontWeight: 700, textTransform: "uppercase" }}>
                            {variation.componentType}
                          </span>
                          <span style={{ fontSize: "0.75rem", color: "#cbd5e1", fontWeight: 600 }}>
                            {variation.label}
                          </span>
                        </div>
                        {variation.note && (
                          <span style={{ fontSize: "0.68rem", color: "#f59e0b", background: "rgba(245, 158, 11, 0.1)", padding: "1px 6px", borderRadius: "4px" }}>
                            {variation.note}
                          </span>
                        )}
                      </div>

                      <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "#f1f5f9", marginBottom: "0.5rem" }}>
                        {variation.question}
                      </div>

                      {/* Interactive UI Component */}
                      {renderInteractiveComponent(variation, caseKey)}

                      {result && (
                        <div style={{ background: "rgba(0,0,0,0.35)", borderRadius: "8px", padding: "0.6rem", margin: "0.5rem 0", fontSize: "0.78rem" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.3rem" }}>
                            <span style={{ color: "#94a3b8" }}>Resolved Answer:</span>
                            <span style={{ color: "#10b981", fontWeight: 700 }}>{result.resolvedAnswer || "(empty)"}</span>
                          </div>

                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", color: "#64748b", fontSize: "0.72rem" }}>
                            <span>Method: {result.resolutionMethod}</span>
                            <span>⚡ {result.latencyMs}ms</span>
                          </div>

                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "0.4rem", paddingTop: "0.4rem", borderTop: "1px solid rgba(255,255,255,0.06)" }}>
                            <span style={{ color: "#94a3b8" }}>Risk Tier:</span>
                            <span style={{ color: result.riskTier === "HIGH_RISK" ? "#f87171" : "#10b981", fontWeight: 700 }}>
                              {result.riskTier === "HIGH_RISK" ? "🛑 HIGH RISK (REVIEW)" : result.riskTier === "UNCERTAIN_BUT_LOW_RISK" ? "⚠️ LOW RISK (AUTO)" : "✅ SAFE (AUTO)"}
                            </span>
                          </div>

                          {result.blockingIssues && result.blockingIssues.length > 0 && (
                            <div style={{ marginTop: "0.4rem", color: "#f87171", fontSize: "0.72rem" }}>
                              ❌ {result.blockingIssues[0].reason}
                            </div>
                          )}
                        </div>
                      )}
                    </div>

                    <button
                      onClick={() => handleTestField(caseKey, variation.question, variation.options || [], group.fieldId)}
                      disabled={isLoading}
                      style={{
                        width: "100%",
                        marginTop: "0.5rem",
                        padding: "0.4rem",
                        background: isLoading ? "#475569" : "rgba(99, 102, 241, 0.15)",
                        border: "1px solid rgba(99, 102, 241, 0.3)",
                        borderRadius: "6px",
                        color: "#818cf8",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        cursor: isLoading ? "not-allowed" : "pointer",
                        transition: "all 0.15s ease",
                      }}
                    >
                      {isLoading ? "Autofilling…" : result ? "🔄 Re-test Autofill" : "⚡ Test Autofill"}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
