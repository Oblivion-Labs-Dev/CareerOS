import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { DisclosureSection } from "./disclosure-section";
import { MetricCard } from "./metric-card";
import { normalizeScoreRange, ScoreGauge } from "./score-gauge";
import { SegmentedControl } from "./segmented-control";
import { StatePanel } from "./state-panel";

describe("normalizeScoreRange", () => {
  it("clamps values to the configured range", () => {
    expect(normalizeScoreRange(120, 0, 100)).toEqual({
      min: 0,
      max: 100,
      value: 100,
      percentage: 100,
    });
  });

  it("falls back to finite values for invalid input", () => {
    expect(normalizeScoreRange(Number.NaN, Number.NaN, Number.NEGATIVE_INFINITY)).toEqual({
      min: 0,
      max: 100,
      value: 0,
      percentage: 0,
    });
  });
});

describe("shared UI foundations", () => {
  it("renders a labelled metric with an accessible trend", () => {
    const markup = renderToStaticMarkup(
      createElement(MetricCard, {
        label: "Processed",
        value: "24k",
        trend: { label: "+8%", direction: "up", tone: "success" },
      }),
    );

    expect(markup).toContain("<article");
    expect(markup).toContain("aria-labelledby=");
    expect(markup).toContain('aria-label="Increasing: +8%"');
  });

  it("renders the gauge as a CSS meter without SVG", () => {
    const markup = renderToStaticMarkup(
      createElement(ScoreGauge, { value: 82, label: "Coverage", tone: "success" }),
    );

    expect(markup).toContain('role="meter"');
    expect(markup).toContain('aria-valuenow="82"');
    expect(markup).toContain("conic-gradient(var(--arsenal-success) 82%");
    expect(markup).not.toContain("<svg");
  });

  it("uses native radios for segmented selection", () => {
    const markup = renderToStaticMarkup(
      createElement(SegmentedControl<string>, {
        label: "Choose a view",
        value: "cards",
        onValueChange: vi.fn(),
        options: [
          { value: "cards", label: "Cards" },
          { value: "table", label: "Table", disabled: true },
        ],
      }),
    );

    expect(markup).toContain("<fieldset");
    expect(markup.match(/type="radio"/g)).toHaveLength(2);
    expect(markup).toContain("checked=\"\"");
    expect(markup).toContain("disabled=\"\"");
  });

  it("keeps disclosure content hidden until expanded", () => {
    const closed = renderToStaticMarkup(
      createElement(DisclosureSection, { title: "Details", children: "Content" }),
    );
    const open = renderToStaticMarkup(
      createElement(DisclosureSection, {
        title: "Details",
        defaultOpen: true,
        children: "Content",
      }),
    );

    expect(closed).toContain("hidden=\"\"");
    expect(closed).toContain('aria-expanded="false"');
    expect(open).not.toContain("hidden=\"\"");
    expect(open).toContain('aria-expanded="true"');
  });

  it("assigns live-region semantics to loading and error states", () => {
    const loading = renderToStaticMarkup(
      createElement(StatePanel, { kind: "loading", title: "Loading" }),
    );
    const error = renderToStaticMarkup(
      createElement(StatePanel, { kind: "error", title: "Failed" }),
    );

    expect(loading).toContain('role="status"');
    expect(loading).toContain('aria-busy="true"');
    expect(error).toContain('role="alert"');
    expect(error).toContain('aria-live="assertive"');
  });
});
