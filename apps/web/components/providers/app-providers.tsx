"use client";

import NextTopLoader from "nextjs-toploader";
import { ThemeProvider } from "next-themes";

export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="data-theme" defaultTheme="dark" enableSystem disableTransitionOnChange>
      <NextTopLoader color="#22d3ee" height={2} showSpinner={false} crawlSpeed={200} />
      {children}
    </ThemeProvider>
  );
}
