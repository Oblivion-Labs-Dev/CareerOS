"use client";

import NextTopLoader from "nextjs-toploader";
import { ThemeProvider } from "next-themes";
import { BackendStatusInit } from "@/lib/backend-status-store";

export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="data-theme" defaultTheme="dark" enableSystem disableTransitionOnChange>
      <BackendStatusInit />
      <NextTopLoader color="#22d3ee" height={2} showSpinner={false} crawlSpeed={400} />
      {children}
    </ThemeProvider>
  );
}
