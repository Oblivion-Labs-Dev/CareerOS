"use client";

import { useTheme } from "next-themes";
import { LightDarkThemeToggle } from "@arsenal/ui";

export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const current = (resolvedTheme ?? theme) === "light" ? "light" : "dark";

  return (
    <LightDarkThemeToggle
      theme={current}
      onToggle={(next) => setTheme(next)}
      className="theme-toggle"
    />
  );
}
