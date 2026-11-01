"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Look chosen by the viewer. "lab" (the default) is the matte material app-wide,
 * slide-panel KPI cards and the combined Autopilot layout; "classic" is the
 * original glass look and flat tiles, kept as a fallback. Stored per browser,
 * so it is a convenience only. MaterialSync mirrors it onto <html>.
 */
export type CardStyle = "classic" | "lab";

const KEY = "careeros.cardStyle";
const EVENT = "careeros:card-style";

// Fallback when storage is blocked, so the switch still works in this tab.
let memory: CardStyle | null = null;

function read(): CardStyle {
  try {
    const saved = window.localStorage.getItem(KEY);
    if (saved === "lab" || saved === "classic") return saved;
  } catch {
    // fall through to the in-memory choice
  }
  return memory ?? "lab";
}

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function useCardStyle(): [CardStyle, (next: CardStyle) => void] {
  const style = useSyncExternalStore(subscribe, read, () => "lab" as CardStyle);
  const set = useCallback((next: CardStyle) => {
    memory = next;
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // Private mode / blocked storage: `memory` keeps it for this tab.
    }
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [style, set];
}
