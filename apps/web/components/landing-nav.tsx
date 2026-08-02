"use client";

import Link from "next/link";
import { primaryLinkClassName } from "@arsenal/ui";
import { ThemeToggle } from "@/components/ui/theme-toggle";

export function LandingNav() {
  return (
    <header className="landing-nav">
      <Link href="/" className="landing-nav-brand">
        <span className="brand-mark">OS</span>
        CareerOS
      </Link>
      <nav className="landing-nav-links">
        <Link href="/apply-pilot">ApplyPilot</Link>
        <Link href="/roadmap">Roadmap</Link>
        <ThemeToggle />
        <Link href="/dashboard" className={`${primaryLinkClassName} btn-primary`}>
          Open Application Dashboard
        </Link>
      </nav>
    </header>
  );
}
