"use client";

import { useEffect, useState } from "react";
import { ThemeProvider } from "next-themes";
import {
  APPLICATION_CARD_STYLE_EVENT,
  applyApplicationCardStyleAttribute,
  readApplicationCardStyle,
} from "@/components/application-assistant/application-card-preferences";
import { BackendStatusInit } from "@/lib/backend-status-store";

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // The application-card style is published on <html> app-wide, not by the
  // cards themselves: the treatment also dresses the surface behind them, and
  // a card cannot paint the page it sits on. Doing it here means every page
  // that shows an application card gets the attribute, including the
  // Applications workspace, which renders a different card component from the
  // one the Settings preview uses.
  useEffect(() => {
    const sync = () => applyApplicationCardStyleAttribute(readApplicationCardStyle());
    sync();
    window.addEventListener(APPLICATION_CARD_STYLE_EVENT, sync);
    return () => window.removeEventListener(APPLICATION_CARD_STYLE_EVENT, sync);
  }, []);

  return (
    <ThemeProvider attribute="data-theme" defaultTheme="dark" enableSystem disableTransitionOnChange>
      <BackendStatusInit />
      {children}
    </ThemeProvider>
  );
}
