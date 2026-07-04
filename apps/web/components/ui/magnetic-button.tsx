import Link from "next/link";
import type { ReactNode } from "react";

interface MagneticButtonProps {
  href: string;
  children: ReactNode;
  variant?: "primary" | "secondary";
  className?: string;
}

export function MagneticButton({ href, children, variant = "primary", className = "" }: MagneticButtonProps) {
  const baseClass = variant === "primary" ? "btn-primary magnetic-button" : "btn-secondary magnetic-button";
  return (
    <Link href={href} className={`${baseClass} ${className}`.trim()}>
      {children}
    </Link>
  );
}
