"use client";

import { SegmentedControl, StatePanel } from "@arsenal/ui";
import { useEffect, useMemo, useState } from "react";
import type { CorpusRecord } from "../corpus-model";
import { dimensionStatus, heatmapDimensionSection, QUALITY_FILTER_OPTIONS, recordMatchesQualityFilter, summarizeBulletReadiness } from "../corpus-quality";
import { BulletHeatmap, QUALITY_STATUS_LABEL, QualityStatusBadge } from "./corpus-quality-ui";
import styles from "../resume-corpus.module.css";

interface AccomplishmentExplorerProps {
  records: CorpusRecord[];
  selectedRecordId?: string;
  onSelect: (record: CorpusRecord, sectionId?: string) => void;
  onCreate: () => void;
}

type ExplorerView = "cards" | "list" | "table" | "timeline" | "kanban" | "matrix" | "quality-map" | "graph";
type ReadinessFilter = CorpusRecord["readiness"] | "all";
type QualityFilter = "all" | (typeof QUALITY_FILTER_OPTIONS)[number]["id"];

interface ExplorerFilters {
  query: string;
  company: string;
  readiness: ReadinessFilter;
  quality: QualityFilter;
}

interface SavedView {
  id: string;
  name: string;
  filters: ExplorerFilters;
}

interface StoredExplorerState {
  view: ExplorerView;
  filters: ExplorerFilters;
  selectedSavedView: string;
  savedViews: SavedView[];
}

const STORAGE_KEY = "careeros.resume-corpus.explorer.v2";

const DEFAULT_FILTERS: ExplorerFilters = {
  query: "",
  company: "all",
  readiness: "all",
  quality: "all",
};

const VIEW_OPTIONS = [
  { value: "cards", label: "Cards" },
  { value: "list", label: "List" },
] as const;

const BUILT_IN_VIEWS: SavedView[] = [
  { id: "all", name: "All accomplishments", filters: DEFAULT_FILTERS },
  {
    id: "ready",
    name: "Ready for reuse",
    filters: { ...DEFAULT_FILTERS, readiness: "ready" },
  },
  {
    id: "review",
    name: "Review queue",
    filters: { ...DEFAULT_FILTERS, readiness: "review" },
  },
  {
    id: "needs-evidence",
    name: "Needs evidence",
    filters: { ...DEFAULT_FILTERS, quality: "no-evidence" },
  },
  {
    id: "high-impact",
    name: "High impact",
    filters: { ...DEFAULT_FILTERS, quality: "high-resume-impact" },
  },
];

const READINESS_COLUMNS: CorpusRecord["readiness"][] = ["draft", "needs-input", "review", "ready"];
const MATRIX_BUCKETS = ["Low", "Developing", "Strong", "Exceptional"] as const;

function clampScore(value: number): number {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
}

function readinessLabel(readiness: CorpusRecord["readiness"]): string {
  return readiness === "needs-input" ? "Needs input" : readiness[0].toUpperCase() + readiness.slice(1);
}

function strongestMetric(record: CorpusRecord) {
  const confidenceRank = { low: 1, medium: 2, high: 3 } as const;
  return [...record.metrics].sort((left, right) => {
    const verificationDelta = Number(right.verification === "verified") - Number(left.verification === "verified");
    if (verificationDelta !== 0) return verificationDelta;
    return confidenceRank[right.confidence] - confidenceRank[left.confidence];
  })[0];
}

function searchableText(record: CorpusRecord): string {
  return [
    record.title,
    record.company,
    record.project,
    record.role,
    record.summary,
    record.currentBullet,
    record.technicalChallenge,
    record.businessImpact,
    record.engineeringImpact,
    record.ownership,
    ...record.technologies,
    ...record.domains,
    ...record.concepts,
    ...record.metrics.flatMap((metric) => [metric.name, metric.value, metric.unit ?? ""]),
  ]
    .join(" ")
    .toLocaleLowerCase();
}

function matchesQuality(record: CorpusRecord, quality: QualityFilter): boolean {
  return quality === "all" || recordMatchesQualityFilter(record, quality);
}

function isExplorerView(value: unknown): value is ExplorerView {
  return VIEW_OPTIONS.some((option) => option.value === value);
}

function isReadinessFilter(value: unknown): value is ReadinessFilter {
  return value === "all" || READINESS_COLUMNS.includes(value as CorpusRecord["readiness"]);
}

function isQualityFilter(value: unknown): value is QualityFilter {
  return value === "all" || QUALITY_FILTER_OPTIONS.some((option) => option.id === value);
}

function sanitizeFilters(value: unknown): ExplorerFilters {
  if (!value || typeof value !== "object") return DEFAULT_FILTERS;
  const candidate = value as Partial<ExplorerFilters>;
  return {
    query: typeof candidate.query === "string" ? candidate.query : "",
    company: typeof candidate.company === "string" ? candidate.company : "all",
    readiness: isReadinessFilter(candidate.readiness) ? candidate.readiness : "all",
    quality: isQualityFilter(candidate.quality) ? candidate.quality : "all",
  };
}

function sanitizeSavedViews(value: unknown): SavedView[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is { id: string; name: string; filters: unknown } => {
      if (!item || typeof item !== "object") return false;
      const candidate = item as Partial<SavedView>;
      return typeof candidate.id === "string" && typeof candidate.name === "string" && Boolean(candidate.name.trim());
    })
    .slice(0, 20)
    .map((item) => ({ id: item.id, name: item.name.trim(), filters: sanitizeFilters(item.filters) }));
}

function bucketForScore(score: number): number {
  return Math.min(3, Math.floor(clampScore(score) / 25));
}

function AccomplishmentCard({
  record,
  selected = false,
  onSelect,
}: {
  record: CorpusRecord;
  selected?: boolean;
  onSelect: () => void;
}) {
  const summary = useMemo(() => summarizeBulletReadiness(record), [record]);
  const metric = strongestMetric(record);
  const interviewStatus = dimensionStatus(record, "interview-readiness");
  const bullet = record.currentBullet || record.summary || "Add a reusable one-line resume bullet.";

  return (
    <article
      className={[styles.accomplishmentCard, selected ? styles.accomplishmentCardSelected : ""].filter(Boolean).join(" ")}
      data-selected={selected ? "true" : undefined}
      role="button"
      tabIndex={0}
      aria-label={"Open " + record.title + " at " + record.company}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onSelect();
      }}
      style={{ cursor: "pointer" }}
    >
      <div className={styles.cardAccent} />
      <div className={styles.cardBody}>
        <div className={styles.cardTopline}>
          <span className={styles.companyLabel}>{record.company || "Company not set"}</span>
          <QualityStatusBadge status={summary.overallStatus} />
        </div>

        <div className={styles.cardTitleButton}>
          <h3>{record.title}</h3>
          <p>{record.project || record.role || "Project not set"}</p>
          <p title={bullet} style={{ WebkitLineClamp: 1 }}>{bullet}</p>
        </div>

        <div className={styles.cardMetric}>
          <span>{metric ? "Best metric · " + metric.name : "Best metric"}</span>
          <strong>{metric ? metric.value + (metric.unit ? " " + metric.unit : "") : "Metric needed"}</strong>
        </div>

        <div className={styles.cardFooter}>
          <span className={styles.resultsMeta}>
            {summary.missingCount} {summary.missingCount === 1 ? "item missing" : "items missing"}
          </span>
          <span className={styles.resultsMeta}>
            Interview: {QUALITY_STATUS_LABEL[interviewStatus]}
          </span>
        </div>
      </div>
    </article>
  );
}

function CardsView({
  records,
  selectedRecordId,
  onSelect,
}: {
  records: CorpusRecord[];
  selectedRecordId?: string;
  onSelect: (record: CorpusRecord) => void;
}) {
  return (
    <div className={styles.cardGrid} aria-label="Accomplishment cards">
      {records.map((record) => (
        <AccomplishmentCard
          key={record.id}
          record={record}
          selected={record.id === selectedRecordId}
          onSelect={() => onSelect(record)}
        />
      ))}
    </div>
  );
}

function CompactListView({ records, onSelect }: { records: CorpusRecord[]; onSelect: (record: CorpusRecord) => void }) {
  return (
    <div className={styles.compactList}>
      <div className={`${styles.compactRow} ${styles.tableHeader}`} aria-hidden="true">
        <span>Accomplishment</span><span>Project</span><span>Metric</span><span>Quality</span><span>Gaps</span>
      </div>
      {records.map((record) => {
        const metric = strongestMetric(record);
        return (
          <button
            type="button"
            className={styles.compactRow}
            key={record.id}
            onClick={() => onSelect(record)}
            aria-label={`Open ${record.title} at ${record.company}`}
          >
            <strong>{record.title} Â· {record.company}</strong>
            <span>{record.project || record.role || "â€”"}</span>
            <span>{metric ? `${metric.name}: ${metric.value}` : "Metric needed"}</span>
            <span>{Math.round(clampScore(record.completeness))}% Â· {readinessLabel(record.readiness)}</span>
            <span>{record.missingInformation.length || "None"}</span>
          </button>
        );
      })}
    </div>
  );
}

function TableView({ records, onSelect }: { records: CorpusRecord[]; onSelect: (record: CorpusRecord) => void }) {
  return (
    <div className={styles.corpusTableWrap}>
      <table className={styles.corpusTable}>
        <caption className={styles.srOnly}>Filtered accomplishment records</caption>
        <thead>
          <tr>
            <th scope="col">Accomplishment</th>
            <th scope="col">Company / project</th>
            <th scope="col">Readiness</th>
            <th scope="col">Strongest metric</th>
            <th scope="col">Impact</th>
            <th scope="col">Evidence</th>
            <th scope="col">Missing</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const metric = strongestMetric(record);
            return (
              <tr key={record.id}>
                <th scope="row">
                  <button type="button" className={styles.tableRecordButton} onClick={() => onSelect(record)}>
                    {record.title}
                  </button>
                </th>
                <td>{record.company}{record.project ? ` Â· ${record.project}` : ""}</td>
                <td>{readinessLabel(record.readiness)}</td>
                <td>{metric ? `${metric.name}: ${metric.value}` : "Metric needed"}</td>
                <td>{Math.round(clampScore(record.impactScore))}</td>
                <td>{Math.round(clampScore(record.evidenceScore))}</td>
                <td>{record.missingInformation.length}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function TimelineView({ records, onSelect }: { records: CorpusRecord[]; onSelect: (record: CorpusRecord) => void }) {
  const ordered = [...records].sort((left, right) => {
    const leftTime = left.updatedAt ? Date.parse(left.updatedAt) : 0;
    const rightTime = right.updatedAt ? Date.parse(right.updatedAt) : 0;
    return rightTime - leftTime || left.title.localeCompare(right.title);
  });

  return (
    <ol className={styles.timeline} style={{ listStyle: "none", paddingLeft: 0 }} aria-label="Accomplishment timeline">
      {ordered.map((record) => (
        <li className={styles.timelineItem} key={record.id}>
          <button type="button" className={styles.timelineButton} onClick={() => onSelect(record)}>
            <small>{record.timePeriod || "Date not set"} Â· {record.company}</small>
            <strong>{record.title}</strong>
            <span>{record.currentBullet || record.summary || "Story details still need to be captured."}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function KanbanView({ records, onSelect }: { records: CorpusRecord[]; onSelect: (record: CorpusRecord) => void }) {
  return (
    <div className={styles.kanbanGrid} aria-label="Accomplishments grouped by readiness">
      {READINESS_COLUMNS.map((readiness) => {
        const columnRecords = records.filter((record) => record.readiness === readiness);
        return (
          <section className={styles.kanbanColumn} key={readiness} aria-labelledby={`kanban-${readiness}`}>
            <div className={styles.kanbanHeader}>
              <span id={`kanban-${readiness}`}>{readinessLabel(readiness)}</span>
              <span>{columnRecords.length}</span>
            </div>
            {columnRecords.length === 0 ? (
              <p className={styles.resultsMeta}>No matching records in this stage.</p>
            ) : columnRecords.map((record) => (
              <button type="button" className={styles.kanbanCard} key={record.id} onClick={() => onSelect(record)}>
                <strong>{record.title}</strong>
                <span>{record.company} Â· {record.completeness}% complete</span>
                <span>{record.missingInformation.length > 0 ? `${record.missingInformation.length} gaps` : "No known gaps"}</span>
              </button>
            ))}
          </section>
        );
      })}
    </div>
  );
}

function MatrixView({ records, onSelect }: { records: CorpusRecord[]; onSelect: (record: CorpusRecord) => void }) {
  return (
    <div>
      <p className={styles.resultsMeta}>Evidence strength increases left to right; impact increases bottom to top.</p>
      <div className={styles.matrix} role="grid" aria-label="Impact by evidence matrix">
        {[3, 2, 1, 0].flatMap((impactBucket) => [
          <div className={styles.matrixLabel} role="rowheader" key={`impact-${impactBucket}`}>
            {MATRIX_BUCKETS[impactBucket]}
          </div>,
          ...[0, 1, 2, 3].map((evidenceBucket) => {
            const cellRecords = records.filter(
              (record) => bucketForScore(record.impactScore) === impactBucket && bucketForScore(record.evidenceScore) === evidenceBucket,
            );
            const label = `${MATRIX_BUCKETS[impactBucket]} impact, ${MATRIX_BUCKETS[evidenceBucket]} evidence`;
            return (
              <div className={styles.matrixCell} role="gridcell" aria-label={label} key={`${impactBucket}-${evidenceBucket}`}>
                {cellRecords.length === 0 ? <span className={styles.srOnly}>No accomplishments</span> : null}
                {cellRecords.map((record) => (
                  <button
                    type="button"
                    className={styles.matrixRecord}
                    key={record.id}
                    onClick={() => onSelect(record)}
                    title={`${record.title}: impact ${record.impactScore}, evidence ${record.evidenceScore}`}
                  >
                    {record.title}
                  </button>
                ))}
              </div>
            );
          }),
        ])}
        <div aria-hidden="true" />
        {[0, 1, 2, 3].map((evidenceBucket) => (
          <div className={styles.matrixLabel} key={`evidence-${evidenceBucket}`}>{MATRIX_BUCKETS[evidenceBucket]}</div>
        ))}
      </div>
    </div>
  );
}

function GraphView({ records, onSelect }: { records: CorpusRecord[]; onSelect: (record: CorpusRecord) => void }) {
  const graphRecords = [...records]
    .sort((left, right) => {
      const scoreDelta = right.impactScore + right.evidenceScore - (left.impactScore + left.evidenceScore);
      return scoreDelta || left.title.localeCompare(right.title);
    })
    .slice(0, 8);

  return (
    <div className={styles.graphPanel}>
      <div className={styles.graphCanvas} aria-label={`Deterministic graph of ${graphRecords.length} accomplishments`}>
        <button
          type="button"
          className={`${styles.graphNode} ${styles.graphNodeCenter}`}
          disabled
          aria-label={`Filtered corpus, ${records.length} records`}
        >
          Filtered corpus<br />{records.length} records
        </button>
        {graphRecords.map((record) => (
          <button
            type="button"
            className={styles.graphNode}
            key={record.id}
            onClick={() => onSelect(record)}
            title={`${record.company}; ${record.technologies.slice(0, 3).join(", ") || "no technologies"}`}
          >
            {record.title}<br />
            <span>{record.company}</span>
          </button>
        ))}
      </div>
      <aside className={styles.panel} aria-label="Graph legend and connections">
        <div className={styles.panelHeader}>
          <div>
            <h2>Bounded knowledge view</h2>
            <p>Top records are ranked deterministically by combined impact and evidence.</p>
          </div>
        </div>
        <div className={styles.recordList}>
          {graphRecords.map((record, index) => (
            <button type="button" className={styles.recordRow} key={record.id} onClick={() => onSelect(record)}>
              <span>{index + 1}</span>
              <span className={styles.rowCopy}>
                <strong>{record.title}</strong>
                <span>{[...record.domains, ...record.technologies].slice(0, 3).join(" Â· ") || "No links captured"}</span>
              </span>
              <span>{Math.round((clampScore(record.impactScore) + clampScore(record.evidenceScore)) / 2)}</span>
            </button>
          ))}
        </div>
        {records.length > graphRecords.length ? (
          <p className={styles.resultsMeta}>Showing 8 of {records.length} records to keep the graph legible and fast.</p>
        ) : null}
      </aside>
    </div>
  );
}

export function AccomplishmentExplorer({ records, selectedRecordId, onSelect, onCreate }: AccomplishmentExplorerProps) {
  const [view, setView] = useState<ExplorerView>("cards");
  const [filters, setFilters] = useState<ExplorerFilters>(DEFAULT_FILTERS);
  const [selectedSavedView, setSelectedSavedView] = useState("all");
  const [savedViews, setSavedViews] = useState<SavedView[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const stored = JSON.parse(raw) as Partial<StoredExplorerState>;
        if (isExplorerView(stored.view)) setView(stored.view);
        setFilters(sanitizeFilters(stored.filters));
        setSavedViews(sanitizeSavedViews(stored.savedViews));
        if (typeof stored.selectedSavedView === "string") setSelectedSavedView(stored.selectedSavedView);
      }
    } catch {
      // A corrupt preference should never block access to the corpus.
    } finally {
      setHydrated(true);
    }
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    const state: StoredExplorerState = { view, filters, selectedSavedView, savedViews };
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Browsers can deny storage; in-memory view state still works for this session.
    }
  }, [filters, hydrated, savedViews, selectedSavedView, view]);

  const companies = useMemo(
    () => [...new Set(records.map((record) => record.company).filter(Boolean))].sort((a, b) => a.localeCompare(b)),
    [records],
  );

  const filtered = useMemo(() => {
    const query = filters.query.trim().toLocaleLowerCase();
    return records.filter((record) => {
      if (filters.company !== "all" && record.company !== filters.company) return false;
      if (filters.readiness !== "all" && record.readiness !== filters.readiness) return false;
      if (!matchesQuality(record, filters.quality)) return false;
      return !query || searchableText(record).includes(query);
    });
  }, [filters, records]);

  const allSavedViews = [...BUILT_IN_VIEWS, ...savedViews];
  const filtersActive = Object.entries(filters).some(([key, value]) => value !== DEFAULT_FILTERS[key as keyof ExplorerFilters]);

  function updateFilter<Key extends keyof ExplorerFilters>(key: Key, value: ExplorerFilters[Key]) {
    setFilters((current) => ({ ...current, [key]: value }));
    setSelectedSavedView("custom");
  }

  function applySavedView(id: string) {
    const savedView = allSavedViews.find((candidate) => candidate.id === id);
    if (!savedView) return;
    setFilters({ ...savedView.filters });
    setSelectedSavedView(id);
  }

  function saveCurrentView() {
    const requestedName = window.prompt("Name this saved filter view:", "My corpus view")?.trim();
    if (!requestedName) return;
    const existing = savedViews.find((savedView) => savedView.name.toLocaleLowerCase() === requestedName.toLocaleLowerCase());
    const next: SavedView = {
      id: existing?.id ?? `saved-${Date.now()}`,
      name: requestedName,
      filters: { ...filters },
    };
    setSavedViews((current) => existing ? current.map((item) => item.id === existing.id ? next : item) : [...current, next]);
    setSelectedSavedView(next.id);
  }

  function clearFilters() {
    setFilters(DEFAULT_FILTERS);
    setSelectedSavedView("all");
  }

  let content;
  switch (view) {
    case "list":
      content = <CompactListView records={filtered} onSelect={onSelect} />;
      break;
    case "table":
      content = <TableView records={filtered} onSelect={onSelect} />;
      break;
    case "timeline":
      content = <TimelineView records={filtered} onSelect={onSelect} />;
      break;
    case "kanban":
      content = <KanbanView records={filtered} onSelect={onSelect} />;
      break;
    case "matrix":
      content = <MatrixView records={filtered} onSelect={onSelect} />;
      break;
    case "quality-map":
      content = <BulletHeatmap records={filtered} onSelectCell={(recordId, dimension) => {
        const record = filtered.find((candidate) => candidate.id === recordId);
        if (record) onSelect(record, heatmapDimensionSection(dimension));
      }} />;
      break;
    case "graph":
      content = <GraphView records={filtered} onSelect={onSelect} />;
      break;
    default:
      content = <CardsView records={filtered} selectedRecordId={selectedRecordId} onSelect={onSelect} />;
  }

  return (
    <div className={styles.viewStack}>
      <div className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Accomplishments</div>
          <h1>Engineering knowledge base</h1>
          <p>Explore the source-of-truth stories that power resumes, interviews, and portfolio narratives.</p>
        </div>
        <button type="button" className={styles.primaryButton} onClick={onCreate}>+ New accomplishment</button>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.toolbarGroup}>
          <input
            className={`${styles.field} ${styles.toolbarSearch}`}
            type="search"
            placeholder="Search company, project, technologyâ€¦"
            value={filters.query}
            onChange={(event) => updateFilter("query", event.currentTarget.value)}
            aria-label="Search accomplishments"
          />
          <select
            className={`${styles.select} ${styles.savedViewSelect}`}
            value={selectedSavedView}
            onChange={(event) => applySavedView(event.currentTarget.value)}
            aria-label="Saved filter view"
          >
            {selectedSavedView === "custom" ? <option value="custom" disabled>Unsaved filters</option> : null}
            {allSavedViews.map((savedView) => <option value={savedView.id} key={savedView.id}>{savedView.name}</option>)}
          </select>
          <button type="button" className={styles.quietButton} onClick={saveCurrentView}>Save view</button>
        </div>

        <SegmentedControl
          label="Explorer layout"
          options={VIEW_OPTIONS}
          value={view}
          onValueChange={setView}
          size="sm"
        />
      </div>

      <div className={styles.toolbar} aria-label="Accomplishment filters">
        <div className={styles.toolbarGroup}>
          <label>
            <span className={styles.srOnly}>Company</span>
            <select
              className={styles.select}
              value={filters.company}
              onChange={(event) => updateFilter("company", event.currentTarget.value)}
            >
              <option value="all">All companies</option>
              {companies.map((company) => <option value={company} key={company}>{company}</option>)}
            </select>
          </label>
          <label>
            <span className={styles.srOnly}>Readiness</span>
            <select
              className={styles.select}
              value={filters.readiness}
              onChange={(event) => updateFilter("readiness", event.currentTarget.value as ReadinessFilter)}
            >
              <option value="all">All readiness</option>
              {READINESS_COLUMNS.map((readiness) => <option value={readiness} key={readiness}>{readinessLabel(readiness)}</option>)}
            </select>
          </label>
          <label>
            <span className={styles.srOnly}>Quality</span>
            <select
              className={styles.select}
              value={filters.quality}
              onChange={(event) => updateFilter("quality", event.currentTarget.value as QualityFilter)}
            >
              <option value="all">All quality</option>
              {QUALITY_FILTER_OPTIONS.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          </label>
          {filtersActive ? <button type="button" className={styles.textButton} onClick={clearFilters}>Clear filters</button> : null}
        </div>
        <span className={styles.resultsMeta} aria-live="polite">{filtered.length} of {records.length} accomplishments</span>
      </div>

      {filtered.length === 0 ? (
        <StatePanel
          kind="empty"
          title={records.length === 0 ? "No accomplishments yet" : "No accomplishments match these filters"}
          description={
            records.length === 0
              ? "Capture the first outcome you want to reuse across resumes and interviews."
              : "Clear or loosen a filter to bring your stories back into view."
          }
          action={
            records.length === 0
              ? <button type="button" className={styles.primaryButton} onClick={onCreate}>Create accomplishment</button>
              : <button type="button" className={styles.quietButton} onClick={clearFilters}>Clear filters</button>
          }
        />
      ) : content}
    </div>
  );
}


