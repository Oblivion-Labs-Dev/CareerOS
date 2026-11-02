"use client";

import { useEffect, useRef, useState } from "react";

const DEFAULT_DURATION_MS = 900;

/** Ease-out cubic: quick off the mark, settling gently on the final value. */
function easeOut(t: number): number {
  return 1 - (1 - t) ** 3;
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export type CountUpOptions = {
  /** How long the climb takes. */
  durationMs?: number;
  /** Hold at zero first, to stagger a row of figures. */
  delayMs?: number;
  /** Decimal places to keep; 0 counts in whole numbers. */
  decimals?: number;
};

/**
 * Count from zero up to `target` whenever that value appears or changes.
 *
 * Dashboards here re-render on a poll, so the animation is keyed on the value
 * itself: it replays when the figure actually changes and stays put across the
 * refreshes that change nothing. Without that guard every poll would restart
 * the count and the numbers would never settle.
 *
 * Returns `target` unchanged when it is null or the viewer has asked for
 * reduced motion.
 */
export function useCountUp(target: number | null, options: CountUpOptions = {}): number | null {
  const { durationMs = DEFAULT_DURATION_MS, delayMs = 0, decimals = 0 } = options;
  const [value, setValue] = useState<number | null>(target === null ? null : 0);
  const frame = useRef<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (target === null) {
      setValue(null);
      return undefined;
    }
    if (prefersReducedMotion() || document.documentElement.dataset.motion === "paused") {
      setValue(target);
      return undefined;
    }

    const factor = 10 ** decimals;
    const round = (n: number) => Math.round(n * factor) / factor;

    setValue(0);

    const begin = () => {
      const start = performance.now();
      const step = (now: number) => {
        if (prefersReducedMotion() || document.documentElement.dataset.motion === "paused") {setValue(target); return;}
        const progress = Math.min(1, (now - start) / durationMs);
        setValue(round(easeOut(progress) * target));
        if (progress < 1) frame.current = requestAnimationFrame(step);
      };
      frame.current = requestAnimationFrame(step);
    };

    if (delayMs > 0) timer.current = setTimeout(begin, delayMs);
    else begin();

    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, [target, durationMs, delayMs, decimals]);

  return value;
}
