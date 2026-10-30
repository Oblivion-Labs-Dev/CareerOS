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
    experimental: {
      optimizePackageImports: ["react-intersection-observer"],
    },
  };
}
