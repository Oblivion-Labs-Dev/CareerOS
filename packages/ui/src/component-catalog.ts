export type ComponentCategory =
  | 'hero'
  | 'cards'
  | 'dashboards'
  | 'data-display'
  | 'controls'
  | 'feedback'
  | 'buttons'
  | 'typography'
  | 'navigation'
  | 'backgrounds'
  | 'motion'
  | 'utilities';

export interface ComponentCatalogEntry {
  id: string;
  name: string;
  description: string;
  category: ComponentCategory;
  importLine: string;
  props: string[];
  usage: string;
  accessibility: string;
  performance: string;
  code: string;
}

export const UI_SETUP_SNIPPET = `// 1. Install shared UI dependencies
pnpm add @career-os/ui framer-motion

// 2. globals.css
@import "@career-os/ui/styles.css";

@tailwind base;
@tailwind components;
@tailwind utilities;

// 3. tailwind.config.ts
import type { Config } from "tailwindcss";
import arsenalPreset from "@career-os/ui/tailwind";

export default {
  presets: [arsenalPreset],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./node_modules/@career-os/ui/dist/**/*.js",
  ],
} satisfies Config;

// 4. Use one component or an entire module
import { GlassCard, NetworkBackground, PrimaryButton } from "@career-os/ui";`;

export const UI_COMPONENT_CATALOG: ComponentCatalogEntry[] = [
  {
    id: 'vault-hero',
    name: 'VaultHeroPattern',
    description:
      'First-screen composition for repository tools: living mesh, hard metrics, and direct module entry.',
    category: 'hero',
    importLine: 'import { NetworkBackground, PrimaryButton } from "@career-os/ui";',
    props: ['NetworkBackground density', 'NetworkBackground accent', 'PrimaryButton forge'],
    usage:
      'Use on product front doors where the background should feel reactive without taking over the workflow.',
    accessibility:
      'Keep all hero copy in regular HTML. The canvas remains decorative and aria-hidden.',
    performance:
      'Use the calm or standard mesh density for full-viewport heroes with other heavy content.',
    code: `import { NetworkBackground, PrimaryButton } from "@career-os/ui";

export function VaultHero() {
  return (
    <section className="relative overflow-hidden rounded-arsenal-lg border border-arsenal-border p-8">
      <NetworkBackground density="standard" accent="ember" />
      <div className="relative z-10 max-w-3xl">
        <p className="text-xs uppercase tracking-[0.24em] text-arsenal-accent">Developer vault</p>
        <h1 className="mt-4 text-5xl font-semibold">Build with context that reacts.</h1>
        <PrimaryButton forge className="mt-6">Open modules</PrimaryButton>
      </div>
    </section>
  );
}`,
  },
  {
    id: 'network-background',
    name: 'NetworkBackground',
    description:
      'Interactive canvas mesh migrated from the portfolio language and rebuilt as a reusable primitive.',
    category: 'backgrounds',
    importLine: 'import { NetworkBackground } from "@career-os/ui";',
    props: [
      'density: calm | standard | dense',
      'accent: ember | cyan | steel',
      'interactive: boolean',
    ],
    usage:
      'Use behind heroes, dashboards, and labs where cursor movement should imply living repository relationships.',
    accessibility: 'Canvas is aria-hidden and respects prefers-reduced-motion.',
    performance:
      'Canvas density is area-aware and capped to avoid runaway particle counts on ultra-wide displays.',
    code: `import { NetworkBackground } from "@career-os/ui";

export function HeroBackdrop() {
  return (
    <section className="relative min-h-[420px] overflow-hidden rounded-arsenal-lg">
      <NetworkBackground density="dense" accent="ember" />
      <div className="relative z-10 p-8">Developer vault content</div>
    </section>
  );
}`,
  },
  {
    id: 'glass-card',
    name: 'GlassCard',
    description: 'Frosted industrial panel with optional glow hover and spring motion.',
    category: 'cards',
    importLine: 'import { GlassCard } from "@career-os/ui";',
    props: ['glow?: boolean', 'className?: string', 'onClick?: () => void'],
    usage: 'Use for repeated modules, dashboard tiles, and component previews.',
    accessibility:
      'Use semantic children. Add button/link semantics outside when the card is an action.',
    performance: 'Small Framer Motion hover transform only; no layout shift.',
    code: `import { GlassCard } from "@career-os/ui";

export function Example() {
  return (
    <GlassCard glow className="max-w-sm">
      <h3 className="font-semibold">Glass surface</h3>
      <p className="mt-2 text-sm text-arsenal-secondary">
        Backdrop blur, border, and hover lift.
      </p>
    </GlassCard>
  );
}`,
  },
  {
    id: 'bento-card',
    name: 'BentoCard',
    description: 'Grid tile with icon slot and optional two-column span.',
    category: 'cards',
    importLine: 'import { BentoCard } from "@career-os/ui";',
    props: ['title: string', 'description: string', 'icon?: ReactNode', 'span?: 1 | 2'],
    usage: 'Use in landing-page bento grids for module summaries and repository capabilities.',
    accessibility: 'Keep headings in document order; decorative icons should be aria-hidden.',
    performance: 'Static markup with no client state.',
    code: `import { BentoCard } from "@career-os/ui";

export function Example() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <BentoCard title="Hybrid retrieval" description="TF-IDF ranking with graph-aware boosts." />
      <BentoCard span="2" title="Budget engine" description="Cap context before the model." />
    </div>
  );
}`,
  },
  {
    id: 'dashboard-card',
    name: 'DashboardCard',
    description: 'Metric tile with value, change line, and trend coloring.',
    category: 'dashboards',
    importLine: 'import { DashboardCard } from "@career-os/ui";',
    props: ['title: string', 'value: string', 'change?: string', 'trend?: up | down | neutral'],
    usage: 'Use for repository health, token savings, test coverage, and deployment metrics.',
    accessibility: 'Trend color is accompanied by text; do not rely on color alone.',
    performance: 'Pure display component suitable for dense dashboard grids.',
    code: `import { DashboardCard } from "@career-os/ui";

export function Example() {
  return <DashboardCard title="Tokens saved" value="92%" change="+14%" trend="up" />;
}`,
  },
  {
    id: 'feature-card',
    name: 'FeatureCard',
    description: 'Compact feature block with optional badge and children slot.',
    category: 'cards',
    importLine: 'import { FeatureCard } from "@career-os/ui";',
    props: ['badge?: string', 'title: string', 'description: string', 'children?: ReactNode'],
    usage: 'Use to describe capability modules and installation paths.',
    accessibility: 'Badge text is plain text, not a status-only color indicator.',
    performance: 'Server-safe component with no effects.',
    code: `import { FeatureCard } from "@career-os/ui";

export function Example() {
  return <FeatureCard badge="Module" title="Knowledge graph" description="Map code relationships." />;
}`,
  },
  {
    id: 'timeline-card',
    name: 'TimelineCard',
    description: 'Roadmap, release, or bootstrap step with optional active highlight.',
    category: 'cards',
    importLine: 'import { TimelineCard } from "@career-os/ui";',
    props: ['year: string', 'title: string', 'description: string', 'active?: boolean'],
    usage: 'Use for setup sequences, migration plans, and release pipelines.',
    accessibility: 'Works inside ordered lists for step-by-step flows.',
    performance: 'Static card; active state only changes classes.',
    code: `import { TimelineCard } from "@career-os/ui";

export function Example() {
  return <TimelineCard year="01" title="Scan repo" description="Build the graph." active />;
}`,
  },
  {
    id: 'section-header',
    name: 'SectionHeader',
    description: 'Page section title with eyebrow, subtitle, and optional action.',
    category: 'typography',
    importLine: 'import { SectionHeader } from "@career-os/ui";',
    props: [
      'eyebrow?: string',
      'title: string',
      'subtitle?: string',
      'action?: ReactNode',
      'align?: left | center',
    ],
    usage: 'Use at the top of major content blocks.',
    accessibility: 'Preserves heading hierarchy through caller-provided placement.',
    performance: 'No runtime effects.',
    code: `import { SectionHeader, PrimaryButton } from "@career-os/ui";

export function Example() {
  return <SectionHeader title="Composable systems" action={<PrimaryButton>Copy</PrimaryButton>} />;
}`,
  },
  {
    id: 'primary-button',
    name: 'PrimaryButton',
    description: 'Accent-filled CTA with magnetic hover motion.',
    category: 'buttons',
    importLine: 'import { PrimaryButton } from "@career-os/ui";',
    props: ['forge?: boolean', 'children: ReactNode', 'onClick?: () => void'],
    usage: 'Use for one primary action in a viewport or panel.',
    accessibility: 'Native button semantics; visible focus inherited from design tokens.',
    performance: 'Small transform animation; honors reduced-motion through global token policy.',
    code: `import { PrimaryButton } from "@career-os/ui";

export function Example() {
  return <PrimaryButton forge>Launch dashboard</PrimaryButton>;
}`,
  },
  {
    id: 'secondary-button',
    name: 'SecondaryButton',
    description: 'Outlined secondary action with magnetic hover.',
    category: 'buttons',
    importLine: 'import { SecondaryButton } from "@career-os/ui";',
    props: ['children: ReactNode', 'onClick?: () => void'],
    usage: 'Use beside a primary CTA or for lower-risk actions.',
    accessibility: 'Native button semantics.',
    performance: 'No expensive effects.',
    code: `import { SecondaryButton } from "@career-os/ui";

export function Example() {
  return <SecondaryButton>View docs</SecondaryButton>;
}`,
  },
  {
    id: 'command-palette',
    name: 'CommandPalette',
    description: 'Keyboard-first command surface for quick navigation and actions.',
    category: 'navigation',
    importLine: 'import { CommandPalette } from "@career-os/ui";',
    props: ['none'],
    usage: 'Mount once near the app root; users open it with Cmd/Ctrl+K.',
    accessibility: 'Uses Radix Dialog primitives for focus trapping and escape handling.',
    performance: 'Idle until opened; command list is small and local.',
    code: `import { CommandPalette } from "@career-os/ui";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <CommandPalette />
    </>
  );
}`,
  },
  {
    id: 'orb-background',
    name: 'OrbBackground',
    description: 'Layered industrial glow for hero sections.',
    category: 'backgrounds',
    importLine: 'import { OrbBackground } from "@career-os/ui";',
    props: ['className?: string'],
    usage: 'Use as a subtle light source behind panels.',
    accessibility: 'aria-hidden decorative layer.',
    performance: 'CSS-only gradients.',
    code: `import { OrbBackground } from "@career-os/ui";

export function Example() {
  return <OrbBackground />;
}`,
  },
  {
    id: 'grid-background',
    name: 'GridBackground',
    description: 'Radial-masked engineering grid overlay.',
    category: 'backgrounds',
    importLine: 'import { GridBackground } from "@career-os/ui";',
    props: ['className?: string'],
    usage: 'Use in hero and dashboard backgrounds to suggest precision.',
    accessibility: 'aria-hidden decorative layer.',
    performance: 'CSS-only background image.',
    code: `import { GridBackground } from "@career-os/ui";

export function Example() {
  return <GridBackground />;
}`,
  },
  {
    id: 'scroll-reveal',
    name: 'ScrollReveal',
    description: 'Intersection-observer entrance animation with direction and delay.',
    category: 'motion',
    importLine: 'import { ScrollReveal } from "@career-os/ui";',
    props: ['direction?: up | down | left | right', 'delay?: number', 'children: ReactNode'],
    usage: 'Use sparingly for narrative page sections.',
    accessibility: 'Global reduced-motion policy disables animation.',
    performance: 'IntersectionObserver avoids scroll listeners.',
    code: `import { ScrollReveal } from "@career-os/ui";

export function Example() {
  return <ScrollReveal direction="up">Revealed content</ScrollReveal>;
}`,
  },
  {
    id: 'badge',
    name: 'Badge',
    description: 'Status and priority pill with variant coloring.',
    category: 'utilities',
    importLine: 'import { Badge } from "@career-os/ui";',
    props: ['variant?: default | progress | p0 | p1 | p2', 'children: ReactNode'],
    usage: 'Use for component states, package status, and risk labels.',
    accessibility: 'Text label remains visible for screen readers and color-blind users.',
    performance: 'Class-only styling.',
    code: `import { Badge } from "@career-os/ui";

export function Example() {
  return <Badge variant="progress">in progress</Badge>;
}`,
  },
  {
    id: 'cn',
    name: 'cn',
    description: 'clsx + tailwind-merge utility for className composition.',
    category: 'utilities',
    importLine: 'import { cn } from "@career-os/ui";',
    props: ['...classes: ClassValue[]'],
    usage: 'Use in every reusable component to compose variants safely.',
    accessibility: 'Not visual; supports stable styling contracts.',
    performance: 'Tiny runtime helper.',
    code: `import { cn } from "@career-os/ui";

const classes = cn("rounded-arsenal p-4", active && "border-arsenal-accent");`,
  },
  {
    id: 'metric-card',
    name: 'MetricCard',
    description: 'Semantic metric summary with trend, description, icon, and action slots.',
    category: 'data-display',
    importLine: 'import { MetricCard } from "@career-os/ui";',
    props: [
      'label: string',
      'value: ReactNode',
      'description?: ReactNode',
      'trend?: MetricTrend',
      'tone?: MetricTone',
      'icon?: ReactNode',
      'action?: ReactNode',
      'className?: string',
    ],
    usage: 'Use for KPI and health summaries across dashboards and review panels.',
    accessibility: 'Trend and tone mapping should stay readable without color alone.',
    performance: 'Pure presentational card with no animation loops.',
    code: `import { MetricCard } from "@career-os/ui";

export function Example() {
  return (
    <MetricCard
      label="Requests processed"
      value="24.8k"
      description="Across the last seven days"
      trend={{ label: "+8.4%", direction: "up", tone: "success" }}
      tone="accent"
    />
  );
}`,
  },
  {
    id: 'score-gauge',
    name: 'ScoreGauge',
    description: 'Accessible CSS conic-gradient meter with clamped values and semantic tones.',
    category: 'data-display',
    importLine: 'import { ScoreGauge } from "@career-os/ui";',
    props: [
      'value: number',
      'min?: number',
      'max?: number',
      'label?: string',
      'description?: ReactNode',
      'tone?: ScoreGaugeTone',
      'size?: ScoreGaugeSize',
      'className?: string',
    ],
    usage: 'Use for coverage, readiness, and quality scores with bounded ranges.',
    accessibility: 'Exposes numeric value textually; meter is decorative surround.',
    performance: 'CSS-only meter with no canvas or frame loops.',
    code: `import { ScoreGauge } from "@career-os/ui";

export function Example() {
  return (
    <ScoreGauge
      value={82}
      label="Coverage score"
      description="82 of 100 checks currently pass."
      tone="success"
    />
  );
}`,
  },
  {
    id: 'segmented-control',
    name: 'SegmentedControl',
    description: 'Typed single-select control backed by native radios for keyboard and form support.',
    category: 'controls',
    importLine: 'import { SegmentedControl } from "@career-os/ui";',
    props: [
      'label: string',
      'options: SegmentedControlOption[]',
      'value: string',
      'onValueChange: (value: string) => void',
      'className?: string',
    ],
    usage: 'Use when a compact exclusive choice needs strong keyboard support.',
    accessibility: 'Native radios preserve focus, labeling, and form semantics.',
    performance: 'No animation dependencies.',
    code: `"use client";

import { useState } from "react";
import { SegmentedControl } from "@career-os/ui";

const options = [
  { value: "cards", label: "Cards" },
  { value: "table", label: "Table" },
  { value: "timeline", label: "Timeline" },
] as const;

export function Example() {
  const [view, setView] = useState<(typeof options)[number]["value"]>("cards");
  return (
    <SegmentedControl
      label="Choose a view"
      options={options}
      value={view}
      onValueChange={setView}
    />
  );
}`,
  },
  {
    id: 'disclosure-section',
    name: 'DisclosureSection',
    description: 'Controlled or uncontrolled accessible section with summary, metadata, and action slots.',
    category: 'controls',
    importLine: 'import { DisclosureSection } from "@career-os/ui";',
    props: [
      'title: string',
      'summary?: ReactNode',
      'meta?: ReactNode',
      'defaultOpen?: boolean',
      'open?: boolean',
      'onOpenChange?: (open: boolean) => void',
      'children: ReactNode',
      'className?: string',
    ],
    usage: 'Use to keep dense secondary content available without crowding the page.',
    accessibility: 'Button trigger with expanded state announcements.',
    performance: 'No heavy motion; layout remains CSS-driven.',
    code: `import { DisclosureSection } from "@career-os/ui";

export function Example() {
  return (
    <DisclosureSection
      title="Implementation details"
      summary="Configuration, limits, and operational notes"
      meta="3 items"
      defaultOpen
    >
      <p>Dense content stays available without overwhelming the surrounding page.</p>
    </DisclosureSection>
  );
}`,
  },
  {
    id: 'state-panel',
    name: 'StatePanel',
    description: 'Consistent empty, loading, and error feedback with live-region semantics.',
    category: 'feedback',
    importLine: 'import { StatePanel } from "@career-os/ui";',
    props: [
      'kind: empty | loading | error',
      'title: string',
      'description?: ReactNode',
      'action?: ReactNode',
      'size?: compact | default',
      'className?: string',
    ],
    usage: 'Use for empty, loading, and error states across product surfaces.',
    accessibility: 'Live-region semantics communicate status changes to assistive tech.',
    performance: 'Lightweight presentational panel.',
    code: `import { StatePanel } from "@career-os/ui";

export function Example() {
  return (
    <StatePanel
      kind="empty"
      title="Nothing here yet"
      description="Create the first item to populate this view."
      action={<button type="button">Create item</button>}
    />
  );
}`,
  },
];

export const COMPONENT_CATEGORIES: { id: ComponentCategory; label: string }[] = [
  { id: 'hero', label: 'Hero' },
  { id: 'cards', label: 'Cards' },
  { id: 'dashboards', label: 'Dashboards' },
  { id: 'data-display', label: 'Data display' },
  { id: 'controls', label: 'Controls' },
  { id: 'feedback', label: 'Feedback' },
  { id: 'typography', label: 'Typography' },
  { id: 'buttons', label: 'Buttons' },
  { id: 'navigation', label: 'Navigation' },
  { id: 'backgrounds', label: 'Backgrounds' },
  { id: 'motion', label: 'Motion' },
  { id: 'utilities', label: 'Utilities' },
];
