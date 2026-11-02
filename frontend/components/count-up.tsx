"use client";

import { useCountUp, type CountUpOptions } from "@/hooks/use-count-up";

type CountUpProps = CountUpOptions & {
  /** The real figure. `null` renders `placeholder` and never animates. */
  value: number | null;
  /** Shown before or instead of a number — an em dash while data is loading. */
  placeholder?: string;
  /** Rendered after the number, inside the same element (e.g. "%", "d"). */
  suffix?: string;
  /** Group thousands, so 1,511 reads as it does elsewhere on the page. */
  locale?: boolean;
  className?: string;
};

/**
 * A figure that counts up from zero when it appears.
 *
 * The accessible name is always the final value: a screen reader should hear
 * "154 applications", not every intermediate number as the count sweeps past.
 */
export function CountUp({
  value,
  placeholder = "—",
  suffix = "",
  locale = false,
  className,
  ...options
}: CountUpProps) {
  const shown = useCountUp(value, options);

  if (value === null || shown === null) {
    return <span className={className}>{placeholder}</span>;
  }

  const text = locale ? shown.toLocaleString() : String(shown);
  const settled = locale ? value.toLocaleString() : String(value);

  return (
    <span className={className} aria-label={`${settled}${suffix}`}>
      <span aria-hidden="true">
        {text}
        {suffix}
      </span>
    </span>
  );
}
