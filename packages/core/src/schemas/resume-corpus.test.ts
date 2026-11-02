import { describe, expect, it } from "vitest";
import {
  careerAccomplishmentSchema,
  corpusMetricSchema,
  reviewerConcernSchema,
} from "./resume-corpus.js";

describe("resume corpus schemas", () => {
  it("applies safe defaults while preserving migration-only legacy fields", () => {
    const parsed = careerAccomplishmentSchema.parse({
      id: "acc-1",
      title: "Reduced onboarding time",
      legacyReviewerPayload: { source: "v1" },
    });

    expect(parsed.readiness).toBe("draft");
    expect(parsed.metrics).toEqual([]);
    expect(parsed.securityConsiderations).toBe("");
    expect(parsed.linkedInVersion).toBe("");
    expect(parsed.legacyReviewerPayload).toEqual({ source: "v1" });
  });

  it("rejects metric records without a value", () => {
    const result = corpusMetricSchema.safeParse({
      id: "metric-1",
      name: "Latency",
      value: "",
    });

    expect(result.success).toBe(false);
  });

  it("rejects reviewer concerns outside the supported severity model", () => {
    const result = reviewerConcernSchema.safeParse({
      id: "concern-1",
      reviewer: "Hiring manager",
      category: "ownership",
      severity: "blocker",
      concern: "The ownership boundary is unclear.",
      relatedAccomplishmentId: "acc-1",
    });

    expect(result.success).toBe(false);
  });
});
