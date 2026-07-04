"use client";

import { useInView } from "react-intersection-observer";
import type { ReactNode } from "react";

interface ScrollRevealProps {
  children: ReactNode;
  delay?: number;
  className?: string;
  direction?: "up" | "left" | "right";
}

export function ScrollReveal({ children, delay = 0, className = "", direction = "up" }: ScrollRevealProps) {
  const { ref, inView } = useInView({
    triggerOnce: true,
    rootMargin: "-60px 0px",
  });

  return (
    <div
      ref={ref}
      className={`scroll-reveal scroll-reveal--${direction}${inView ? " is-visible" : ""}${className ? ` ${className}` : ""}`}
      style={{ transitionDelay: `${delay}s` }}
    >
      {children}
    </div>
  );
}
