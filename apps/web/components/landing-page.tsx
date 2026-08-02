"use client";

import Link from "next/link";
import { GlassCard, ScrollReveal, cn, primaryLinkClassName, secondaryLinkClassName } from "@arsenal/ui";
import { LandingFirefoxInstall } from "@/components/landing-firefox-install";
import { LandingNav } from "@/components/landing-nav";

const MODULES = [
  {
    tag: "Live now",
    icon: "⚡",
    title: "ApplyPilot",
    description:
      "Chrome extension that detects job forms, autofills your profile, attaches resumes, and learns unknown fields.",
    accent: "var(--accent)",
  },
  {
    tag: "Foundation",
    icon: "◈",
    title: "Profile OS",
    description: "One canonical profile — contact info, work authorization, screening defaults — synced everywhere.",
    accent: "var(--accent-secondary)",
  },
  {
    tag: "Coming next",
    icon: "◎",
    title: "Application Intelligence",
    description: "Track every application, generate cover letters, and answer custom ATS questions with context.",
    accent: "var(--accent-tertiary)",
  },
];

const FEATURES = [
  { icon: "🎯", title: "Smart Autofill", desc: "Learns ATS fields and fills applications in seconds." },
  { icon: "📊", title: "Career Analytics", desc: "Track funnel metrics from apply to offer." },
  { icon: "✉️", title: "Documents", desc: "Resumes and cover letters tied to each opportunity." },
  { icon: "🔗", title: "Unified Profile", desc: "One source of truth synced across every tool." },
  { icon: "🧠", title: "Question AI", desc: "Answer screening questions with your real experience." },
  { icon: "🗺️", title: "Roadmap OS", desc: "See what's shipping and what's next, transparently." },
];

const STATS = [
  { value: "1-click", label: "Apply flow" },
  { value: "AI", label: "Powered intelligence" },
  { value: "∞", label: "Applications tracked" },
];

export function LandingPage() {
  return (
    <div className="landing">
      <LandingNav />

      <main>
      <section className="landing-hero">
        <span className="landing-eyebrow landing-fade-in landing-fade-in--1">
          <span className="landing-eyebrow-pulse" />
          AI-powered career operating system
        </span>

        <h1 className="landing-title landing-fade-in landing-fade-in--2">
          Your career,
          <br />
          <span className="landing-title-accent">orchestrated</span>
        </h1>

        <p className="landing-subtitle landing-fade-in landing-fade-in--3">
          CareerOS brings together job autofill, application tracking, resume intelligence, and career analytics in
          one calm, premium workspace. Start with ApplyPilot and grow into the full stack.
        </p>

        <div className="landing-cta landing-fade-in landing-fade-in--4">
          <Link href="/dashboard" className={primaryLinkClassName}>
            Open Application Dashboard
          </Link>
          <Link href="/apply-pilot" className={secondaryLinkClassName}>
            Get ApplyPilot
          </Link>
        </div>

        <LandingFirefoxInstall />

        <ScrollReveal>
          <div className="landing-flow">
            <span>Browser Extension</span>
            <span className="landing-flow-arrow">→</span>
            <span>CareerOS API</span>
            <span className="landing-flow-arrow">→</span>
            <span>Application Dashboard</span>
          </div>
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          <div className="landing-stats">
            {STATS.map((stat) => (
              <div key={stat.label} className="landing-stat">
                <div className="landing-stat-value">{stat.value}</div>
                <div className="landing-stat-label">{stat.label}</div>
              </div>
            ))}
          </div>
        </ScrollReveal>
      </section>

      <section className="landing-modules">
        {MODULES.map((mod, i) => (
          <ScrollReveal key={mod.title} delay={i * 0.08}>
            <GlassCard glow className="landing-module-card h-full">
              <span className="landing-module-tag">{mod.tag}</span>
              <div
                className="landing-feature-icon"
                style={{ background: `color-mix(in srgb, ${mod.accent} 15%, transparent)` }}
              >
                {mod.icon}
              </div>
              <h3 className="font-semibold">{mod.title}</h3>
              <p className="mt-2 text-sm text-arsenal-secondary">{mod.description}</p>
            </GlassCard>
          </ScrollReveal>
        ))}
      </section>

      <section className="landing-section">
        <ScrollReveal>
          <h2 className="landing-section-title">
            Everything you need to <span className="landing-title-accent">win the search</span>
          </h2>
          <p className="landing-section-sub">
            A modular career stack that grows with you — from your first autofill to full application intelligence.
          </p>
        </ScrollReveal>

        <div className="landing-features-grid">
          {FEATURES.map((feat, i) => (
            <ScrollReveal key={feat.title} delay={i * 0.05}>
              <div className="landing-feature-item">
                <div className="landing-feature-icon">{feat.icon}</div>
                <h4>{feat.title}</h4>
                <p>{feat.desc}</p>
              </div>
            </ScrollReveal>
          ))}
        </div>
      </section>

      <section className="landing-section" style={{ paddingTop: 0 }}>
        <ScrollReveal>
          <div className="landing-cta-band">
            <h2>Ready to ship your next application?</h2>
            <p>Install ApplyPilot, wire your profile, and let CareerOS handle the rest.</p>
            <div className="landing-cta" style={{ marginBottom: 0 }}>
              <Link href="/apply-pilot" className={primaryLinkClassName}>
                Get ApplyPilot
              </Link>
              <Link href="/roadmap" className={cn(secondaryLinkClassName)}>
                View Roadmap
              </Link>
            </div>
          </div>
        </ScrollReveal>
      </section>
      </main>

      <footer className="landing-footer">CareerOS · Built on Arsenal · ApplyPilot MVP in progress</footer>
    </div>
  );
}
