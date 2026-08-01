"use client";

type MarketPoint = { date: string; share: number };

type MarketTrends = {
  available: boolean;
  country: string;
  series: MarketPoint[];
  latestShare: number | null;
  latestDate?: string;
  changeSince2019: number | null;
  source: string;
};

export function MarketTrendsChart({ market }: { market: MarketTrends | null | undefined }) {
  if (!market?.available || !market.series.length) {
    return (
      <section className="panel p-md">
        <h2 className="text-sm font-medium mb-sm">AI job market (US)</h2>
        <p className="muted text-sm">
          Indeed Hiring Lab dataset not found locally. Place <code>AI_posting.csv</code> in{" "}
          <code>apps/api/data/market/</code> to enable this chart.
        </p>
      </section>
    );
  }

  const width = 480;
  const height = 140;
  const padding = 24;
  const points = market.series;
  const minY = Math.min(...points.map((p) => p.share));
  const maxY = Math.max(...points.map((p) => p.share));
  const rangeY = Math.max(maxY - minY, 0.5);

  const path = points
    .map((point, index) => {
      const x = padding + (index / Math.max(points.length - 1, 1)) * (width - padding * 2);
      const y = height - padding - ((point.share - minY) / rangeY) * (height - padding * 2);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <section className="panel p-md">
      <div className="flex flex-wrap items-baseline justify-between gap-sm mb-md">
        <div>
          <h2 className="text-sm font-medium">AI job market ({market.country})</h2>
          <p className="muted text-sm">
            Share of postings mentioning AI keywords · latest {market.latestShare}% ({market.latestDate})
            {market.changeSince2019 != null ? ` · +${market.changeSince2019} pts since 2019` : ""}
          </p>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label="AI posting share trend">
        <path d={path} fill="none" stroke="var(--cos-accent, #3b82f6)" strokeWidth="2" />
      </svg>
      <p className="muted text-xs mt-sm">{market.source}</p>
    </section>
  );
}
