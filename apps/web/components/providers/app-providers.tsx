"use client";

import { useEffect, useState } from "react";
import { ThemeProvider } from "next-themes";
import { BackendStatusInit } from "@/lib/backend-status-store";
import { useAtmosphere } from "@/hooks/use-atmosphere";

function AtmosphereSync() {
  const [atmosphere] = useAtmosphere();
  useEffect(() => {
    document.documentElement.dataset.atmosphere = atmosphere;
  }, [atmosphere]);
  return null;
}

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <ThemeProvider attribute="data-theme" defaultTheme="dark" enableSystem>
      <BackendStatusInit />
      <AtmosphereSync />
      {children}
    </ThemeProvider>
  );
}
