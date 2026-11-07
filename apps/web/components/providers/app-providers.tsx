"use client";

import { useEffect, useState } from "react";
import { ThemeProvider } from "next-themes";
import { BackendStatusInit } from "@/lib/backend-status-store";
import { useCardStyle } from "@/hooks/use-card-style";
import { useAtmosphere } from "@/hooks/use-atmosphere";

/** Lab's matte material applies app-wide, so the card-style choice is mirrored
 *  onto <html> where the global stylesheet can see it. */
function MaterialSync() {
  const [style] = useCardStyle();
  useEffect(() => {
    document.documentElement.dataset.material = style === "lab" ? "matte" : "glass";
  }, [style]);
  return null;
}

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
      <MaterialSync />
      <AtmosphereSync />
      {children}
    </ThemeProvider>
  );
}
