"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { MarketTrendsChart } from "@/components/analytics/market-trends-chart";
import { getClientApiBaseUrl } from "@/lib/api";

type AnalyticsSummary = {
  total: number;
  buckets: Record<string, number>;
  sectors: Record<string, number>;
  channels: Record<string, number>;
  rejectionRate: number;
  interviewRate: number;
  rows: Array<{
    date: string;
    company: string;
    role: string;
    sector: string;
    channel: string;
    bucket: string;
    notes: string;
    url: string;
  }>;
  generatedAt: string;
};

type MarketTrends = {
  available: boolean;
  country: string;
  series: Array<{ date: string; share: number }>;
  latestShare: number | null;
  latestDate?: string;
  changeSince2019: number | null;
  source: string;
};

type AnalyticsResponse = {
  success: boolean;
  summary: AnalyticsSummary;
  outcomeArchives: Array<{ folder: string; status: string }>;
  marketTrends?: MarketTrends;
};

const BUCKET_COLORS: Record<string, string> = {
  Active: "var(--cos-info)",
  Interview: "var(--cos-warning)",
  Offer: "#8b5cf6",
  Hired: "var(--cos-success)",
  "Rejected/Closed": "var(--cos-danger)",
};

export function JobSearchAnalytics() {
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/analytics/summary`, { cache: "no-store" });
      if (!res.ok) throw new Error("Failed to load analytics");
      setData(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="muted">Loading analytics…</p>;
  if (error) return <p className="text-danger">{error}</p>;
  if (!data?.summary) return <p className="muted">No analytics data yet.</p>;

  const { summary, outcomeArchives, marketTrends } = data;
  const reportUrl = `${getClientApiBaseUrl()}/analytics/report`;

  return (
    <div className="stack gap-lg">
      <div className="flex flex-wrap gap-md items-center justify-between">
        <p className="muted text-sm max-w-xl">
          Your pipeline at a glance — funnel, channels, and optional labor-market context.
        </p>
        <div className="flex gap-sm">
          <a className="btn btn-secondary" href={reportUrl} target="_blank" rel="noopener noreferrer">
            Full HTML report
          </a>
          <Link className="btn btn-primary" href="/dashboard#applications">
            Pipeline
          </Link>
        </div>
      </div>

      <MarketTrendsChart market={marketTrends} />

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-md">
        <StatCard label="Total" value={summary.total} />
        {Object.entries(summary.buckets).map(([label, count]) => (
          <StatCard key={label} label={label} value={count} accent={BUCKET_COLORS[label]} />
        ))}
      </div>

      <div className="grid md:grid-cols-2 gap-md">
        <Panel title="Conversion">
          <p>Interview rate: <strong>{summary.interviewRate}%</strong></p>
          <p>Rejection rate (closed): <strong>{summary.rejectionRate}%</strong></p>
        </Panel>
        <Panel title="Outcome archives">
          {outcomeArchives.length === 0 ? (
            <p className="muted text-sm">Record outcomes from Applications to build a learning archive.</p>
          ) : (
            <ul className="text-sm stack gap-xs">
              {outcomeArchives.slice(0, 5).map((item) => (
                <li key={item.folder}>
                  <strong>{item.folder.replace(/_/g, " ")}</strong> — {item.status}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel title="Recent applications">
        {summary.rows.length === 0 ? (
          <p className="muted">No applications tracked yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left p-sm">Date</th>
                  <th className="text-left p-sm">Company</th>
                  <th className="text-left p-sm">Role</th>
                  <th className="text-left p-sm">Status</th>
                  <th className="text-left p-sm">Notes</th>
                </tr>
              </thead>
              <tbody>
                {summary.rows.slice(0, 10).map((row, index) => (
                  <tr key={`${row.company}-${row.role}-${index}`} className="border-t border-border">
                    <td className="p-sm">{row.date?.slice(0, 10)}</td>
                    <td className="p-sm">{row.company}</td>
                    <td className="p-sm">{row.role}</td>
                    <td className="p-sm">
                      <span
                        className="inline-block px-2 py-0.5 rounded-full text-xs text-white"
                        style={{ background: BUCKET_COLORS[row.bucket] || "#64748b" }}
                      >
                        {row.bucket}
                      </span>
                    </td>
                    <td className="p-sm muted truncate max-w-[240px]">{row.notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="panel p-md">
      <div className="text-xs uppercase muted">{label}</div>
      <div className="text-2xl font-semibold mt-1" style={accent ? { color: accent } : undefined}>
        {value}
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel p-md">
      <h2 className="text-sm font-medium mb-md">{title}</h2>
      {children}
    </section>
  );
}
