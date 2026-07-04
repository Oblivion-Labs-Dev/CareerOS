"use client";

import Link from "next/link";
import { MagneticButton } from "@/components/ui/magnetic-button";
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
        <MagneticButton href="/applications">Open Tracker</MagneticButton>
      </nav>
    </header>
  );
}
