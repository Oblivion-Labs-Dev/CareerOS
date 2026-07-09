import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const rootDir = path.dirname(fileURLToPath(import.meta.url));
const arsenalUi = path.resolve(rootDir, "../../../Arsenal/packages/ui");
const arsenalMotion = path.resolve(rootDir, "../../../Arsenal/packages/motion");

const nextConfig: NextConfig = {
  transpilePackages: ["@career-os/core", "@career-os/ui", "@arsenal/ui", "@arsenal/motion"],
  experimental: {
    optimizePackageImports: ["react-intersection-observer", "nextjs-toploader"],
  },
  turbopack: {
    resolveAlias: {
      "@arsenal/ui": arsenalUi,
      "@arsenal/ui/tailwind": path.join(arsenalUi, "tailwind.preset.ts"),
      "@arsenal/motion": arsenalMotion,
    },
  },
  webpack: (config) => {
    config.resolve.alias = {
      ...config.resolve.alias,
      "@arsenal/ui": arsenalUi,
      "@arsenal/motion": arsenalMotion,
    };
    return config;
  },
};

export default nextConfig;
