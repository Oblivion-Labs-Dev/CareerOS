import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

export default function nextConfig(phase: string): NextConfig {
  return {
    // Production builds get their own output folder so `next build` never
    // writes into the .next that a running `next dev` is serving from, and
    // switching between dev and prod (scripts/restart-dev.ps1 -Prod) keeps
    // both warm.
    distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next" : ".next-prod",
    transpilePackages: ["@career-os/core", "@career-os/ui"],
    // Dashboard is a tab of Autopilot now, and Browse Jobs / HN Hiring are gone:
    // every scraped job (HN included) already flows through filters into the
    // Autopilot queue, so old links land there instead of on a 404.
    async redirects() {
      return [
        { source: "/dashboard", destination: "/applications?tab=dashboard", permanent: false },
        { source: "/jobs/discover", destination: "/applications?tab=queued", permanent: false },
        { source: "/jobs/hacker-news", destination: "/applications?tab=queued", permanent: false },
      ];
    },
    experimental: {
      optimizePackageImports: ["react-intersection-observer"],
    },
  };
}
