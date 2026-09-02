"use client";

import { MagneticButton } from "./magnetic-button";
import { cn } from "./lib/cn";
import { type ReactNode } from "react";

interface SectionHeaderProps {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  align?: "left" | "center";
  className?: string;
  action?: ReactNode;
}

export function SectionHeader({
  eyebrow,
  title,
  subtitle,
  align = "center",
  className,
  action,
}: SectionHeaderProps) {
  return (
    <div
      className={cn(
        "mb-12 max-w-3xl",
        align === "center" && "mx-auto text-center",
        className,
      )}
    >
      {eyebrow && (
        <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-arsenal-accent">
          {eyebrow}
        </p>
      )}
      <div className={cn("flex items-end justify-between gap-4", align === "center" && "flex-col items-center")}>
        <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">{title}</h2>
        {action}
      </div>
      {subtitle && <p className="mt-4 text-lg text-arsenal-secondary">{subtitle}</p>}
    </div>
  );
}

interface PrimaryButtonProps {
  children: ReactNode;
  className?: string;
  forge?: boolean;
  onClick?: () => void;
}

export function PrimaryButton({ children, className, forge, onClick }: PrimaryButtonProps) {
  return (
    <MagneticButton
      onClick={onClick}
      data-cursor={forge ? "forge" : "button"}
      className={cn(
        "inline-flex items-center justify-center rounded-full px-6 py-3 text-xs font-bold uppercase tracking-wider",
        "bg-gradient-to-r from-arsenal-accent to-orange-500 text-black shadow-arsenal-glow",
        "transition-all duration-250 ease-out hover:brightness-110 hover:scale-[1.04] active:scale-[0.98]",
        className,
      )}
    >
      {children}
    </MagneticButton>
  );
}

export function SecondaryButton({ children, className, onClick }: PrimaryButtonProps) {
  return (
    <MagneticButton
      onClick={onClick}
      data-cursor="button"
      className={cn(
        "inline-flex items-center justify-center rounded-full border border-arsenal-border px-6 py-3 text-xs font-semibold uppercase tracking-wider",
        "bg-arsenal-elevated/40 text-arsenal-primary backdrop-blur-md",
        "transition-all duration-250 ease-out hover:border-arsenal-accent/80 hover:bg-arsenal-elevated hover:scale-[1.04] active:scale-[0.98]",
        className,
      )}
    >
      {children}
    </MagneticButton>
  );
}
