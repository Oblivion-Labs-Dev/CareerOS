import { cva, type VariantProps } from "class-variance-authority";
import { type ReactNode } from "react";
import { cn } from "./lib/cn";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-wide capitalize",
  {
    variants: {
      variant: {
        default: "border-arsenal-border bg-arsenal-elevated text-arsenal-secondary",
        accent: "border-arsenal-accent/30 bg-arsenal-accent/10 text-arsenal-accent",
        success: "border-arsenal-success/30 bg-arsenal-success/10 text-arsenal-success",
        danger: "border-arsenal-danger/30 bg-arsenal-danger/10 text-arsenal-danger",
        warning: "border-amber-500/30 bg-amber-500/10 text-amber-400",
        planned: "border-slate-400/25 bg-slate-400/10 text-arsenal-muted",
        progress: "border-arsenal-accent/30 bg-arsenal-accent/10 text-arsenal-accent",
        done: "border-arsenal-success/30 bg-arsenal-success/10 text-arsenal-success",
        p0: "border-arsenal-danger/30 bg-arsenal-danger/10 text-arsenal-danger",
        p1: "border-orange-500/30 bg-orange-500/10 text-orange-400",
        p2: "border-amber-500/30 bg-amber-500/10 text-amber-400",
        p3: "border-violet-500/30 bg-violet-500/10 text-violet-400",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps extends VariantProps<typeof badgeVariants> {
  children: ReactNode;
  className?: string;
}

export function Badge({ children, variant, className }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)}>{children}</span>;
}
