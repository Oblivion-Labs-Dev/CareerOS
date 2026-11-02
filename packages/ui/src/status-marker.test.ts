import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StatusMarker } from "./status-marker";

describe("StatusMarker", () => {
  it("renders an icon, visible label, and associated assistive description", () => {
    const markup = renderToStaticMarkup(
      createElement(StatusMarker, {
        icon: "!",
        label: "Needs attention",
        description: "Supporting evidence has not been attached.",
        tone: "warning",
      }),
    );

    expect(markup).toContain('data-tone="warning"');
    expect(markup).toContain('aria-describedby="');
    expect(markup).toContain('aria-hidden="true"');
    expect(markup).toContain("Needs attention");
    expect(markup).toContain("Supporting evidence has not been attached.");
  });

  it("keeps the label visible in compact mode and supports optional hover text", () => {
    const markup = renderToStaticMarkup(
      createElement(StatusMarker, {
        compact: true,
        icon: "✓",
        label: "Ready",
        description: "All required checks passed.",
        title: "All required checks passed.",
        tone: "success",
      }),
    );

    expect(markup).toContain('data-compact="true"');
    expect(markup).toContain('title="All required checks passed."');
    expect(markup).toContain(">Ready</span>");
  });

  it("preserves a caller-provided accessible description reference", () => {
    const markup = renderToStaticMarkup(
      createElement(StatusMarker, {
        "aria-describedby": "external-description",
        icon: "?",
        label: "Unknown",
        description: "This status has not been evaluated.",
      }),
    );

    expect(markup).toMatch(/aria-describedby="external-description [^"]+-description"/);
  });
});
