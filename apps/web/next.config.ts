import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@career-os/core", "@career-os/ui"],
  experimental: {
    optimizePackageImports: ["react-intersection-observer", "nextjs-toploader"],
  },
};

export default nextConfig;
