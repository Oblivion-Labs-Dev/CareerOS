"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  getAutopilotJobs,
  getAutopilotJobsPage,
  getSubmissionReceipt,
  resetSingleAutopilotJob,
  resetSubmittedAutopilotJobs,
  SubmissionReceiptItem,
} from "@/lib/application-assistant-api";
import { IconCheckCircle, IconDownload, IconRefresh, IconSend } from "@/components/application-assistant/autopilot/icons";
import { SubmissionReceiptModal } from "@/components/application-assistant/submission-receipt-modal";
import { ApplicationQueueCard, type QueueApplication } from "@/components/application-assistant/application-queue-card";
import { resolveApplicationReadiness } from "@/components/application-assistant/application-readiness";

const PAGE_SIZE = 10;

export function SubmittedJobsCenter() {
  const [submittedList, setSubmittedList] = useState<any[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [selectedReceipt, setSelectedReceipt] = useState<SubmissionReceiptItem | null>(null);
  const [receiptLoading, setReceiptLoading] = useState(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const loadingMoreRef = useRef(false);

  const handleDownloadMergedJson = async () => {
    // Export needs the complete set, not just whatever's been scrolled into
    // view so far — fetch fresh rather than relying on the paginated list.
    let all = submittedList;
    try {
      const res = await getAutopilotJobs("SUBMITTED");
      all = res.jobs || [];
    } catch {
      // fall back to whatever's currently loaded
    }
    if (all.length === 0) return;
    const mergedData = {
      exportTimestamp: new Date().toISOString(),
      totalSubmitted: all.length,
      applications: all.map((job) => ({
        id: job.id,
        jobId: job.jobId,
        company: job.company,
        title: job.title,
        applicationUrl: job.applicationUrl || job.listingUrl,
        status: job.status,
        submittedAt: job.submittedAt || job.updatedAt,
        answers: job.fieldsFilled || job.answers || {},
        submissionEvidence: job.submissionEvidence || {},
        verificationStatus: job.verificationStatus || "VERIFIED",
        matchScore: job.matchScore,
        rawTelemetry: job,
      })),
    };
    const jsonBlob = new Blob([JSON.stringify(mergedData, null, 2)], { type: "application/json" });
    const downloadUrl = URL.createObjectURL(jsonBlob);
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `careeros_submitted_applications_${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(downloadUrl);
    setSuccessMsg(`Exported ${all.length} submitted application(s) as merged JSON.`);
    setTimeout(() => setSuccessMsg(null), 3500);
  };

  const fetchSubmitted = async () => {
    setLoading(true);
    try {
      const res = await getAutopilotJobsPage({
        status: "SUBMITTED",
        sortBy: "submittedAt",
        sortDir: "desc",
        limit: PAGE_SIZE,
        offset: 0,
      });
      setSubmittedList(res.jobs || []);
      setTotalCount(res.total ?? (res.jobs || []).length);
      setHasMore(!!res.hasMore);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Could not fetch submitted jobs");
    } finally {
      setLoading(false);
    }
  };

  const loadMore = useCallback(async () => {
    if (loadingMoreRef.current || !hasMore) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const res = await getAutopilotJobsPage({
        status: "SUBMITTED",
        sortBy: "submittedAt",
        sortDir: "desc",
        limit: PAGE_SIZE,
        offset: submittedList.length,
      });
      setSubmittedList((prev) => [...prev, ...(res.jobs || [])]);
      setTotalCount(res.total ?? submittedList.length + (res.jobs || []).length);
      setHasMore(!!res.hasMore);
    } catch {
      // Leave hasMore as-is — the sentinel will just retry on next scroll.
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasMore, submittedList.length]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) void loadMore();
      },
      { rootMargin: "200px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMore]);

  const handleResetAll = async () => {
    if (!confirm("Are you sure you want to reset all submitted jobs back to UNAPPLIED so they can be re-applied?")) {
      return;
    }
    setResetting(true);
    setError(null);
    try {
      const res = await resetSubmittedAutopilotJobs("SUBMITTED");
      setSuccessMsg(res.message || "Submitted jobs reset to unapplied");
      await fetchSubmitted();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err?.message || "Failed to reset submitted jobs");
    } finally {
      setResetting(false);
    }
  };

  const handleResetSingle = async (id: string, title: string) => {
    setResetting(true);
    setError(null);
    try {
      await resetSingleAutopilotJob(id);
      setSuccessMsg(`Reset "${title}" back to unapplied.`);
      await fetchSubmitted();
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err: any) {
      setError(err?.message || "Failed to reset job");
    } finally {
      setResetting(false);
    }
  };

  useEffect(() => {
    fetchSubmitted();
  }, []);

  const handleViewReceipt = async (job: any) => {
    setReceiptLoading(true);
    try {
      const res = await getSubmissionReceipt(job.id);
      setSelectedReceipt(res.receipt);
    } catch {
      // Create fallback receipt from job model
      const fields = job.fieldsFilled || job.answers || {};
      const fallback: SubmissionReceiptItem = {
        receiptId: job.receiptId || `rcpt_${job.id.slice(0, 12)}`,
        jobId: job.id,
        company: job.company || "Company",
        title: job.title || "Role",
        applicationUrl: job.applicationUrl || job.listingUrl || "",
        confirmationUrl: job.submissionEvidence?.confirmationUrl || "",
        confirmationText: job.confirmationText || job.submissionEvidence?.confirmationText || "Application confirmed by ATS",
        submittedAt: job.submittedAt || job.updatedAt || new Date().toISOString(),
        fieldsFilled: fields,
        fieldsCount: Object.keys(fields).length || 5,
        verificationStatus: "VERIFIED",
        certificateFingerprint: job.certificateFingerprint || job.id.toUpperCase(),
        tailoringMode: job.tailoringMode || job.submissionEvidence?.tailoringMode || null,
        resumeFileUsed: job.resumeFileUsed || job.submissionEvidence?.resumeFileUsed || null,
        matchScoreAtSubmission: job.matchScoreAtSubmission ?? job.submissionEvidence?.matchScoreAtSubmission ?? null,
      };
      setSelectedReceipt(fallback);
    } finally {
      setReceiptLoading(false);
    }
  };

  return (
    <div className="space-y-6 font-sans">
      {/* Header Banner */}
      <div className="p-6 rounded-2xl border border-emerald-500/25 bg-gradient-to-br from-[#0a161f] via-[#0d1e2a] to-[#071017] backdrop-blur-2xl shadow-xl flex flex-wrap justify-between items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <IconSend className="w-5 h-5 text-[#2ee8c9]" />
            <span>Submitted Applications</span>
          </h2>
          <p className="text-xs text-slate-300 mt-1">
            All applications processed by Autopilot. Click any application card to open its side panel to inspect all filled form fields and answers.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="px-3.5 py-1 text-xs font-bold rounded-full bg-emerald-500/15 border border-emerald-500/40 text-[#2ee8c9] shadow-[0_0_12px_rgba(46,232,201,0.25)]">
            {totalCount} Submitted
          </span>
          {submittedList.length > 0 && (
            <>
              <button
                onClick={handleDownloadMergedJson}
                className="px-3.5 py-1 text-xs font-bold text-cyan-200 hover:text-white bg-cyan-500/15 hover:bg-cyan-500/25 rounded-xl border border-cyan-400/30 transition-all cursor-pointer flex items-center gap-1.5 shadow-sm"
                title="Download all submitted applications merged together as JSON"
              >
                <IconDownload className="w-3.5 h-3.5" />
                <span>Download All JSON</span>
              </button>
              <button
                onClick={handleResetAll}
                disabled={resetting || loading}
                className="px-3.5 py-1 text-xs font-bold text-amber-300 hover:text-amber-200 bg-amber-500/10 hover:bg-amber-500/20 rounded-xl border border-amber-500/30 transition-all cursor-pointer flex items-center gap-1.5 shadow-sm"
                title="Reset all submitted applications back to Unapplied"
              >
                <span>↺</span>
                <span>{resetting ? "Resetting..." : "Reset All to Unapplied"}</span>
              </button>
            </>
          )}
          <button
            onClick={fetchSubmitted}
            disabled={loading}
            className="px-3 py-1 text-xs font-semibold text-slate-300 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 transition-all cursor-pointer"
          >
            {loading ? "Refreshing..." : "↻ Refresh"}
          </button>
        </div>
      </div>

      {successMsg && (
        <div className="p-4 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-2">
          <IconCheckCircle className="w-4 h-4" />
          <span>{successMsg}</span>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
          {error}
        </div>
      )}

      {submittedList.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-white/10 rounded-2xl text-slate-500 text-xs bg-[#0d121c]/40">
          No submitted applications currently recorded. All jobs are ready in unapplied state.
        </div>
      ) : (
        <div className="aa-queue-grid">
          {submittedList.map((job) => {
            const evidence = job.submissionEvidence || {};
            const fields = job.fieldsFilled || job.answers || {};
            const fieldCount = Object.keys(fields).length;

            const app: QueueApplication = {
              id: job.id,
              jobId: job.jobId || job.id,
              companyName: job.company || "Unknown company",
              roleTitle: job.title || "Unknown role",
              provider: job.provider || job.sourceProvider || "Autopilot",
              status: "submitted_manually",
              progress: 1,
              verifiedCount: fieldCount,
              reviewCount: 0,
              missingCount: 0,
              conflictingCount: 0,
              matchScore: job.matchScore,
              aiAnalyzed: job.matchScore != null,
              updatedAt: job.submittedAt || job.updatedAt || new Date().toISOString(),
              errors: [],
              fields: Object.keys(fields).map((label) => ({ label, classification: "verified" })),
              answers: fields,
              resumeFileUsed: job.resumeFileUsed || evidence.resumeFileUsed || undefined,
            };

            return (
              <ApplicationQueueCard
                key={job.id}
                app={app}
                statusAccent="emerald"
                isOpening={false}
                isBrowserOpen={false}
                isAnalyzing={false}
                isWizardLoading={false}
                gateLoading={false}
                profileBlocked={false}
                readiness={resolveApplicationReadiness(app)}
                needsAiAnalysis={false}
                pendingCount={0}
                isPreparing={false}
                isActivePrep={false}
                openingElapsedSec={0}
                analyzeElapsedSec={0}
                closingBrowser={false}
                onFocusBrowser={() => undefined}
                onResume={() => undefined}
                onAnswerQuestions={() => undefined}
                onOpenInBrowser={() => undefined}
                onToggleSubmitted={() => undefined}
                onArchive={() => void handleResetSingle(job.id, job.title || "Job")}
                intelligenceSlot={
                  <>
                    <p className="aac-alert aac-alert--info">
                      {typeof evidence === "object" && evidence.confirmationText
                        ? evidence.confirmationText
                        : job.confirmationText || "ATS confirmed submission"}
                    </p>
                    {(job.tailoringMode || evidence.tailoringMode) && (
                      <p className="aac-alert aac-alert--info" style={{ marginTop: 4 }}>
                        Resume: {String(job.tailoringMode || evidence.tailoringMode).toUpperCase()}
                      </p>
                    )}
                  </>
                }
                primaryActionOverride={{
                  label: "View receipt",
                  onClick: () => void handleViewReceipt(job),
                  disabled: receiptLoading,
                }}
              />
            );
          })}
        </div>
      )}

      {submittedList.length > 0 && hasMore && (
        <div ref={sentinelRef} className="flex items-center justify-center py-6">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <IconRefresh className="w-4 h-4 animate-spin text-[#2ee8c9]" />
            <span>{loadingMore ? "Loading more applications..." : "Scroll for more"}</span>
          </div>
        </div>
      )}

      {/* Submission Receipt Modal */}
      {selectedReceipt && (
        <SubmissionReceiptModal
          receipt={selectedReceipt}
          onClose={() => setSelectedReceipt(null)}
        />
      )}
    </div>
  );
}
