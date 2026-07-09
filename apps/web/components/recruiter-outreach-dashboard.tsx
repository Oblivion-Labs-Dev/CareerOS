"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Tooltip } from "@arsenal/ui";
import { getClientApiBaseUrl } from "@/lib/api";
interface OutreachResult {
  id: string;
  company: string;
  recruiterName: string;
  firstName?: string;
  email: string;
  subject: string;
  status: "sent" | "failed" | "dry_run" | "pending" | "paused" | "retrying" | string;
  deliveryStatus?: "delivered" | "bounced" | "failed" | "pending" | string;
  messageId?: string | null;
  sentAt?: string | null;
  error?: string | null;
}

interface DeliveryStats {
  delivered: number;
  bounced: number;
  undelivered: number;
  invalid: number;
  sendFailed?: number;
  pending?: number;
  bounceMessages?: number;
}

interface OutreachCampaign {
  id: string;
  label: string;
  startedAt: string;
  completedAt?: string | null;
  status: string;
  dryRun?: boolean;
  throttle?: {
    enabled?: boolean;
    delaySeconds?: number;
    jitterSeconds?: number;
  };
  summary: {
    total: number;
    sent: number;
    failed: number;
    pending?: number;
  };
  deliveryStats?: DeliveryStats;
  resultsTotal?: number;
  recentLimit?: number;
  results: OutreachResult[];
}

interface OutreachCampaignsResponse {
  success: boolean;
  campaigns: OutreachCampaign[];
  count: number;
  aggregateDeliveryStats?: DeliveryStats;
  source?: string;
}

function formatDateTime(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatDuration(startedAt?: string, completedAt?: string | null) {
  if (!startedAt || !completedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = new Date(completedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return "—";
  const minutes = Math.round((end - start) / 60000);
  if (minutes < 1) return "< 1 min";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function deliveryLabel(result: OutreachResult) {
  if (result.deliveryStatus === "delivered") return "Delivered";
  if (result.deliveryStatus === "bounced") return "Bounced";
  if (result.deliveryStatus === "failed") return "Send failed";
  if (result.deliveryStatus === "pending") return "Pending";
  return result.status.replaceAll("_", " ");
}

function deliveryPillClass(result: OutreachResult) {
  if (result.deliveryStatus === "delivered") return "outreach-status-pill--sent";
  if (result.deliveryStatus === "bounced") return "outreach-status-pill--bounced";
  if (result.deliveryStatus === "failed") return "outreach-status-pill--failed";
  return `outreach-status-pill--${result.status}`;
}

interface MetricCardProps {
  label: string;
  value: number;
  hint: string;
  tooltip: string;
  variant?: "success" | "warn" | "danger" | "";
}

interface MetricBreakdownItem {
  label: string;
  value: number;
  tooltip: string;
  tone?: "warn" | "danger" | "muted";
}

interface NonDeliveredGroupProps {
  total: number;
  items: MetricBreakdownItem[];
  tooltip: string;
}

function MetricTooltipBox({
  tooltip,
  className = "",
  children,
}: {
  tooltip: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Tooltip content={tooltip} side="right" className={className}>
      {children}
    </Tooltip>
  );
}

function MetricCard({ label, value, hint, tooltip, variant = "" }: MetricCardProps) {
  const variantClass = variant ? `outreach-metric-card--${variant}` : "";
  return (
    <MetricTooltipBox
      tooltip={tooltip}
      className={`dashboard-metric-card outreach-metric-card ${variantClass}`.trim()}
    >
      <span className="outreach-metric-label">{label}</span>
      <strong>{value}</strong>
      <p>{hint}</p>
    </MetricTooltipBox>
  );
}

function NonDeliveredGroup({ total, items, tooltip }: NonDeliveredGroupProps) {
  return (
    <div className="dashboard-metric-card outreach-metric-card outreach-metric-card--group outreach-metric-card--danger">
      <MetricTooltipBox tooltip={tooltip} className="outreach-metric-group-header-wrap">
        <div className="outreach-metric-group-header">
          <span className="outreach-metric-label">Non-delivered</span>
          <strong>{total}</strong>
        </div>
      </MetricTooltipBox>
      <div className="outreach-metric-breakdown" role="list" aria-label="Non-delivered breakdown by type">
        {items.map((item) => (
          <MetricTooltipBox
            key={item.label}
            tooltip={item.tooltip}
            className={`outreach-metric-breakdown-row${item.tone ? ` outreach-metric-breakdown--${item.tone}` : ""}`}
          >
            <div className="outreach-metric-breakdown-row-inner" role="listitem">
              <span className="outreach-metric-breakdown-label">{item.label}</span>
              <span className="outreach-metric-breakdown-value">{item.value}</span>
            </div>
          </MetricTooltipBox>
        ))}
      </div>
    </div>
  );
}

const METRIC_TOOLTIPS = {
  delivered:
    "Gmail sent these and we have not received a bounce-back yet. They likely reached the recruiter's inbox.",
  nonDelivered:
    "All emails that did not successfully reach the recruiter — bounced, failed to send, or not sent yet.",
  bounced:
    "Gmail accepted the send, but the recipient's mail server later rejected it. You should see a 'Delivery failed' notice in your Gmail.",
  sendFailed:
    "Gmail rejected the send before it left your account — for example, daily sending limit errors.",
  invalid:
    "Email addresses confirmed bad from bounce messages — wrong, outdated, or no longer active at that company.",
  pending: "Not sent yet. These are still queued in the campaign batch.",
  accepted:
    "Gmail accepted these outgoing messages from our script. This does not guarantee they reached the recruiter; some may still bounce later.",
  total: "Total recruiters in this campaign batch, including sent, failed, and not-yet-sent.",
} as const;

export function RecruiterOutreachDashboard() {
  const [campaigns, setCampaigns] = useState<OutreachCampaign[]>([]);
  const [aggregateStats, setAggregateStats] = useState<DeliveryStats | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadCampaigns = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/email/outreach-campaigns?limit=20&recent_limit=10`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error("Could not load outreach campaigns");
      const data = (await res.json()) as OutreachCampaignsResponse;
      const nextCampaigns = data.campaigns || [];
      setCampaigns(nextCampaigns);
      setAggregateStats(data.aggregateDeliveryStats ?? null);
      setSelectedCampaignId((current) => current || nextCampaigns[0]?.id || "");
    } catch {
      setCampaigns([]);
      setAggregateStats(null);
      setError("Could not load recruiter outreach results. Start the API on port 8000.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCampaigns();
  }, [loadCampaigns]);

  const selectedCampaign = useMemo(
    () => campaigns.find((campaign) => campaign.id === selectedCampaignId) ?? campaigns[0],
    [campaigns, selectedCampaignId],
  );

  const stats = selectedCampaign?.deliveryStats ?? aggregateStats;

  const nonDeliveredTotal = useMemo(() => {
    if (!stats) return 0;
    return (stats.bounced ?? 0) + (stats.sendFailed ?? 0) + (stats.pending ?? 0);
  }, [stats]);

  const nonDeliveredBreakdown = useMemo<MetricBreakdownItem[]>(() => {
    if (!stats) return [];
    return [
      {
        label: "Bounced",
        value: stats.bounced ?? 0,
        tooltip: METRIC_TOOLTIPS.bounced,
        tone: "warn",
      },
      {
        label: "Send failed",
        value: stats.sendFailed ?? 0,
        tooltip: METRIC_TOOLTIPS.sendFailed,
        tone: "danger",
      },
      {
        label: "Invalid addresses",
        value: stats.invalid ?? 0,
        tooltip: METRIC_TOOLTIPS.invalid,
        tone: "muted",
      },
      {
        label: "Pending",
        value: stats.pending ?? 0,
        tooltip: METRIC_TOOLTIPS.pending,
        tone: "muted",
      },
    ];
  }, [stats]);

  const recentResults = useMemo(() => {
    if (!selectedCampaign) return [];
    return [...selectedCampaign.results].sort((a, b) => {
      const aTime = a.sentAt || "";
      const bTime = b.sentAt || "";
      return bTime.localeCompare(aTime);
    });
  }, [selectedCampaign]);

  return (
    <div className="outreach-dashboard">
      <section className="dashboard-metric-grid outreach-metric-grid" aria-label="Delivery metrics">
        <MetricCard
          label="Delivered"
          value={stats?.delivered ?? 0}
          hint="Landed without bounce or send error"
          tooltip={METRIC_TOOLTIPS.delivered}
          variant="success"
        />
        <NonDeliveredGroup
          total={nonDeliveredTotal}
          items={nonDeliveredBreakdown}
          tooltip={METRIC_TOOLTIPS.nonDelivered}
        />
        <MetricCard
          label="Accepted by Gmail"
          value={selectedCampaign?.summary.sent ?? 0}
          hint={`${stats?.bounceMessages ?? 0} bounce notices in Gmail`}
          tooltip={METRIC_TOOLTIPS.accepted}
        />
        <MetricCard
          label="Campaign total"
          value={selectedCampaign?.summary.total ?? 0}
          hint={`${campaigns.length} saved batches`}
          tooltip={METRIC_TOOLTIPS.total}
        />
      </section>

      <article className="dashboard-panel dashboard-panel--wide outreach-panel">
        <div className="dashboard-panel-header outreach-panel-header">
          <div className="outreach-panel-title">
            <span className="toc-card-kicker">Outreach results</span>
            <h2>{loading ? "Loading campaigns…" : selectedCampaign?.label || "No campaigns yet"}</h2>
            {selectedCampaign ? (
              <p className="muted dashboard-panel-copy">
                {selectedCampaign.status.replaceAll("_", " ")} · started {formatDateTime(selectedCampaign.startedAt)}
                {selectedCampaign.completedAt ? ` · finished ${formatDateTime(selectedCampaign.completedAt)}` : ""}
                {selectedCampaign.completedAt
                  ? ` · duration ${formatDuration(selectedCampaign.startedAt, selectedCampaign.completedAt)}`
                  : ""}
                {selectedCampaign.throttle?.enabled
                  ? ` · throttle ${selectedCampaign.throttle.delaySeconds ?? 0}s + ${selectedCampaign.throttle.jitterSeconds ?? 0}s jitter`
                  : ""}
              </p>
            ) : (
              <p className="muted dashboard-panel-copy">
                Run <code>send_recruiter_outreach_batch.py</code> to save campaign results for this dashboard.
              </p>
            )}
          </div>
          <div className="outreach-dashboard-actions">
            {campaigns.length > 1 ? (
              <label className="outreach-campaign-select">
                Campaign
                <select
                  value={selectedCampaign?.id || ""}
                  onChange={(event) => setSelectedCampaignId(event.target.value)}
                  disabled={loading}
                >
                  {campaigns.map((campaign) => (
                    <option key={campaign.id} value={campaign.id}>
                      {campaign.label} ({campaign.summary.sent}/{campaign.summary.total})
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <button type="button" className="btn btn-sm" onClick={() => void loadCampaigns()} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </div>

        {error ? <p className="email-sender-status email-sender-status--warn">{error}</p> : null}

        {selectedCampaign && recentResults.length ? (
          <>
            <p className="outreach-recent-note muted">
              Showing {recentResults.length} most recent of {selectedCampaign.resultsTotal ?? recentResults.length} total
            </p>
            <div className="outreach-results-table-wrap">
              <table className="outreach-results-table">
                <thead>
                  <tr>
                    <th>Delivery</th>
                    <th>Company</th>
                    <th>Recruiter</th>
                    <th>Email</th>
                    <th>Sent</th>
                  </tr>
                </thead>
                <tbody>
                  {recentResults.map((result) => (
                    <tr key={result.id}>
                      <td>
                        <span className={`outreach-status-pill ${deliveryPillClass(result)}`}>
                          {deliveryLabel(result)}
                        </span>
                        {result.error ? <span className="outreach-result-error">{result.error}</span> : null}
                      </td>
                      <td className="outreach-company-cell">{result.company}</td>
                      <td className="outreach-name-cell">{result.recruiterName}</td>
                      <td className="outreach-email-cell">
                        <a href={`mailto:${result.email}`} title={result.email}>
                          {result.email}
                        </a>
                      </td>
                      <td className="outreach-date-cell">{formatDateTime(result.sentAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="muted dashboard-empty">
            {loading ? "Loading outreach campaign results…" : "No recruiter outreach campaigns saved yet."}
          </p>
        )}
      </article>
    </div>
  );
}
