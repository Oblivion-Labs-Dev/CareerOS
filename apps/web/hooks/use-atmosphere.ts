"use client";

import { useCallback, useSyncExternalStore } from "react";

export type Atmosphere = "cinematic" | "standard";

const KEY = "careeros.atmosphere";
const EVENT = "careeros:atmosphere";

let memory: Atmosphere | null = null;

function read(): Atmosphere {
  try {
    const saved = window.localStorage.getItem(KEY);
    if (saved === "cinematic" || saved === "standard") return saved;
  } catch {
    // fall through to the in-memory choice
  }
  return memory ?? "cinematic";
}

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function useAtmosphere(): [Atmosphere, (next: Atmosphere) => void] {
  const atmosphere = useSyncExternalStore(subscribe, read, () => "cinematic" as Atmosphere);
  const set = useCallback((next: Atmosphere) => {
    memory = next;
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // In-memory preference remains available when storage is blocked.
    }
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [atmosphere, set];
}
