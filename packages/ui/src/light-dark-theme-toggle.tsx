"use client";

import { useEffect, useState } from "react";
import { cn } from "./lib/cn";

type ThemeMode = "light" | "dark";

export interface LightDarkThemeToggleProps {
  className?: string;
  /** Called when user toggles — wire to next-themes `setTheme` in your app. */
  onToggle?: (next: ThemeMode) => void;
  /** Current resolved theme from next-themes or your own state. */
  theme?: ThemeMode;
}

export function LightDarkThemeToggle({ className, onToggle, theme = "dark" }: LightDarkThemeToggleProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return (
      <button type="button" className={cn(toggleClassName, className)} aria-label="Toggle theme">
        <span className="h-[18px] w-[18px]" />
      </button>
    );
  }

  const isDark = theme === "dark";

  return (
    <button
      type="button"
      className={cn(toggleClassName, className)}
      onClick={() => onToggle?.(isDark ? "light" : "dark")}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Light mode" : "Dark mode"}
    >
      {isDark ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-[18px] w-[18px]">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-[18px] w-[18px]">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      )}
    </button>
  );
}

const toggleClassName =
  "inline-flex h-9 w-9 items-center justify-center rounded-full border border-arsenal-border bg-arsenal-elevated text-arsenal-secondary transition hover:border-arsenal-accent hover:text-arsenal-primary";
