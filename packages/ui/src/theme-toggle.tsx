"use client";

import { useEffect, useState } from "react";
import { cn } from "./lib/cn";

const THEMES = ["deep-forge", "obsidian-cyber", "ivory-graphite"] as const;
const STORAGE_KEY = "arsenal-theme";
const DEFAULT_THEME = "deep-forge";

export function ThemeToggle({ className }: { className?: string }) {
  const [theme, setTheme] = useState<string>(DEFAULT_THEME);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    const initial =
      stored && THEMES.includes(stored as (typeof THEMES)[number]) ? stored : DEFAULT_THEME;
    setTheme(initial);
    document.documentElement.setAttribute("data-theme", initial);
  }, []);

  const cycle = () => {
    const idx = THEMES.indexOf(theme as (typeof THEMES)[number]);
    const next = THEMES[(idx + 1) % THEMES.length]!;
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(STORAGE_KEY, next);
  };

  return (
    <button
      type="button"
      onClick={cycle}
      className={cn(
        "rounded-full border border-arsenal-border bg-arsenal-elevated px-4 py-2 text-sm text-arsenal-secondary transition hover:border-arsenal-accent hover:text-arsenal-primary",
        className,
      )}
    >
      Theme: {theme.replace(/-/g, " ")}
    </button>
  );
}
