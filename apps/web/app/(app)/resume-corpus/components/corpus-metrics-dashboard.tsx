"use client";

import { MetricCard, SegmentedControl } from "@arsenal/ui";
import { useMemo, useState } from "react";
import { CorpusEmptyState } from "@career-os/ui/corpus";
import type { CorpusRecord } from "../corpus-model";
import styles from "../resume-corpus.module.css";

interface CorpusMetricsDashboardProps {
  records: CorpusRecord[];
  onSelectRecord: (recordId: string) => void;
}

type MetricView = "impact" | "company" | "domain" | "verification";
type GroupFilter = { kind: "company" | "domain"; value: string } | null;

export function CorpusMetricsDashboard({ records, onSelectRecord }: CorpusMetricsDashboardProps) {
  const [view, setView] = useState<MetricView>("impact");
  const [groupFilter, setGroupFilter] = useState<GroupFilter>(null);

  const allMetrics = useMemo(
    () =>
      records.flatMap((record) =>
        record.metrics.map((metric) => ({
          ...metric,
          recordId: record.id,
          recordTitle: record.title,
          company: record.company,
          domain: record.domains[0] ?? "General",
        })),
      ),
    [records],
  );

  const stats = useMemo(() => {
    const verified = allMetrics.filter((metric) => metric.verification === "verified").length;
    const missingOpportunities = records.filter((record) => record.metrics.length === 0).length;
    const byCompany = new Map<string, number>();
    const byDomain = new Map<string, number>();
    allMetrics.forEach((metric) => {
      byCompany.set(metric.company, (byCompany.get(metric.company) ?? 0) + 1);
      byDomain.set(metric.domain, (byDomain.get(metric.domain) ?? 0) + 1);
    });
    return { verified, missingOpportunities, byCompany, byDomain };
  }, [allMetrics, records]);

  const sortedMetrics = useMemo(() => {
    const filteredMetrics = groupFilter
      ? allMetrics.filter((metric) => metric[groupFilter.kind] === groupFilter.value)
      : allMetrics;
    if (view === "verification") {
      return [...filteredMetrics].sort((left, right) => {
        const rank = (value: string) => (value === "verified" ? 2 : value === "needs-evidence" ? 1 : 0);
        return rank(right.verification) - rank(left.verification);
      });
    }
    if (view === "company") {
      return [...filteredMetrics].sort((left, right) => left.company.localeCompare(right.company));
    }
    if (view === "domain") {
      return [...filteredMetrics].sort((left, right) => left.domain.localeCompare(right.domain));
    }
    return [...filteredMetrics].sort((left, right) => right.value.length - left.value.length);
  }, [allMetrics, groupFilter, view]);

  if (records.length === 0) {
    return (
      <CorpusEmptyState
        title="No metrics yet"
        description="Metrics turn impact into comparable, verifiable data. Add accomplishments and attach structured metrics."
      />
    );
  }

  return (
    <div className={styles.viewStack}>
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Metrics</div>
          <h1>Structured impact intelligence</h1>
          <p>Track verified metrics, missing quantification opportunities, and coverage by company and domain.</p>
        </div>
        <SegmentedControl
          label="Metric grouping"
          value={view}
          onValueChange={(value) => {
            setView(value as MetricView);
            setGroupFilter(null);
          }}
          options={[
            { value: "impact", label: "Highest impact" },
            { value: "company", label: "By company" },
            { value: "domain", label: "By domain" },
            { value: "verification", label: "Verification" },
          ]}
        />
      </header>

      <div className={styles.metricsGrid}>
        <MetricCard label="Total metrics" value={String(allMetrics.length)} description="Structured quantified claims" tone="accent" />
        <MetricCard label="Verified" value={String(stats.verified)} description="Backed by evidence or source" tone="success" />
        <MetricCard label="Missing metrics" value={String(stats.missingOpportunities)} description="Accomplishments without quantified impact" tone="danger" />
        <MetricCard label="Companies" value={String(stats.byCompany.size)} description="Organizations with metric coverage" tone="accent" />
        <MetricCard label="Domains" value={String(stats.byDomain.size)} description="Technical domains represented" tone="accent" />
        <MetricCard label="Unverified" value={String(allMetrics.length - stats.verified)} description="Need source or evidence" tone="danger" />
      </div>

      <section className={styles.panel}>
        <div className={styles.panelHeader}>
          <div>
            <h2>{groupFilter ? `${groupFilter.value} metrics` : view === "impact" ? "Highest-impact metrics" : view === "company" ? "Metrics by company" : view === "domain" ? "Metrics by domain" : "Verification status"}</h2>
            <p>Click a row to open the related accomplishment.</p>
          </div>
          {groupFilter ? <button type="button" className={styles.quietButton} onClick={() => setGroupFilter(null)}>Clear chart filter</button> : null}
        </div>

        {sortedMetrics.length === 0 ? (
          <CorpusEmptyState
            title="No structured metrics attached"
            description="Add metrics to accomplishments to compare impact across roles and domains."
            actionLabel="Open accomplishments"
            onAction={() => onSelectRecord(records[0]?.id ?? "")}
          />
        ) : (
          <div className={styles.compactList}>
            {sortedMetrics.map((metric) => (
              <button
                key={metric.id}
                type="button"
                className={styles.compactRow}
                onClick={() => onSelectRecord(metric.recordId)}
              >
                <span>
                  <strong>{metric.name}: {metric.value}{metric.unit ? ` ${metric.unit}` : ""}</strong>
                  <span>{metric.recordTitle} · {metric.company}</span>
                </span>
                <span className={styles.statusTag}>{metric.verification.replace("-", " ")}</span>
                <span className={styles.statusTag}>{metric.confidence} confidence</span>
              </button>
            ))}
          </div>
        )}
      </section>

      <div className={styles.chartGrid}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}><h3>By company</h3></div>
          <div className={styles.barChart} aria-label="Metrics by company">
            {Array.from(stats.byCompany.entries()).map(([company, count]) => (
              <button key={company} type="button" className={`${styles.barRow} ${styles.barButton}`} aria-pressed={groupFilter?.kind === "company" && groupFilter.value === company} onClick={() => { setView("company"); setGroupFilter({ kind: "company", value: company }); }}>
                <span>{company}</span>
                <span className={styles.barTrack} role="progressbar" aria-label={`${company}: ${count} metrics`} aria-valuemin={0} aria-valuemax={allMetrics.length} aria-valuenow={count}><span className={styles.barFill} style={{ width: `${Math.min(100, count * 20)}%` }} /></span>
                <output>{count}</output>
              </button>
            ))}
          </div>
        </section>
        <section className={styles.panel}>
          <div className={styles.panelHeader}><h3>By domain</h3></div>
          <div className={styles.barChart} aria-label="Metrics by domain">
            {Array.from(stats.byDomain.entries()).map(([domain, count]) => (
              <button key={domain} type="button" className={`${styles.barRow} ${styles.barButton}`} aria-pressed={groupFilter?.kind === "domain" && groupFilter.value === domain} onClick={() => { setView("domain"); setGroupFilter({ kind: "domain", value: domain }); }}>
                <span>{domain}</span>
                <span className={styles.barTrack} role="progressbar" aria-label={`${domain}: ${count} metrics`} aria-valuemin={0} aria-valuemax={allMetrics.length} aria-valuenow={count}><span className={styles.barFill} style={{ width: `${Math.min(100, count * 20)}%` }} /></span>
                <output>{count}</output>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
