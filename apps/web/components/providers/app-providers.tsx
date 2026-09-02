"use client";

import { useEffect, useState } from "react";
import { ThemeProvider } from "next-themes";
import { BackendStatusInit } from "@/lib/backend-status-store";

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <ThemeProvider attribute="data-theme" defaultTheme="dark" enableSystem disableTransitionOnChange>
      <BackendStatusInit />
      {children}
    </ThemeProvider>
  );
}
