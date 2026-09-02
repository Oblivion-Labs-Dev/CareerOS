"use client";

import { useInView } from "react-intersection-observer";
import { type ReactNode } from "react";
import { cn } from "./lib/cn";

interface ScrollRevealProps {
  children: ReactNode;
  delay?: number;
  className?: string;
  direction?: "up" | "left" | "right";
}

const directionOffset: Record<NonNullable<ScrollRevealProps["direction"]>, string> = {
  up: "translate-y-7",
  left: "-translate-x-7",
  right: "translate-x-7",
};

export function ScrollReveal({
  children,
  delay = 0,
  className,
  direction = "up",
}: ScrollRevealProps) {
  const { ref, inView } = useInView({
    triggerOnce: true,
    rootMargin: "-60px 0px",
  });

  return (
    <div
      ref={ref}
      className={cn(
        "opacity-0 transition-[opacity,transform] duration-500 ease-out motion-reduce:opacity-100 motion-reduce:transform-none",
        directionOffset[direction],
        inView && "translate-x-0 translate-y-0 opacity-100",
        className,
      )}
      style={{ transitionDelay: `${delay}s` }}
    >
      {children}
    </div>
  );
}
