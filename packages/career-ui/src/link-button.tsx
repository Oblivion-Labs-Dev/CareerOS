"use client";

import { type ReactNode } from "react";
import { cn } from "./lib/cn";

export const primaryLinkClassName =
  "inline-flex items-center justify-center rounded-full px-6 py-3 text-sm font-semibold bg-arsenal-accent text-arsenal-background shadow-arsenal-glow transition hover:brightness-110";

export const secondaryLinkClassName =
  "inline-flex items-center justify-center rounded-full border border-arsenal-border px-6 py-3 text-sm font-semibold bg-arsenal-elevated text-arsenal-primary transition hover:border-arsenal-accent";

interface LinkButtonProps {
  href: string;
  children: ReactNode;
  className?: string;
}

export function PrimaryLink({ href, children, className }: LinkButtonProps) {
  return (
    <a href={href} className={cn(primaryLinkClassName, className)}>
      {children}
    </a>
  );
}

export function SecondaryLink({ href, children, className }: LinkButtonProps) {
  return (
    <a href={href} className={cn(secondaryLinkClassName, className)}>
      {children}
    </a>
  );
}
