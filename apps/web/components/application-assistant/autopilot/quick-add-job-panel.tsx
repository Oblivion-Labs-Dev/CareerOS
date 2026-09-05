"use client";

import React, { useState } from "react";
import { enqueueJobForAutopilot } from "@/lib/application-assistant-api";

type TailoringMode = "off" | "honest" | "aggressive";

export function QuickAddJobPanel({ onAdded }: { onAdded?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const [applicationUrl, setApplicationUrl] = useState("");
  const [tailoringMode, setTailoringMode] = useState<TailoringMode>("honest");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const reset = () => {
    setCompany("");
    setTitle("");
    setLocation("");
    setApplicationUrl("");
    setTailoringMode("honest");
  };

  const handleSubmit = async () => {
    if (!company.trim() || !title.trim() || !applicationUrl.trim()) {
      setMessage({ tone: "error", text: "Company, title, and application URL are all required." });
      return;
    }
    setSubmitting(true);
    setMessage(null);
    try {
      const res = await enqueueJobForAutopilot({
        company: company.trim(),
        title: title.trim(),
        location: location.trim(),
        applicationUrl: applicationUrl.trim(),
        tailoringMode,
      });
      if (res.success === false || (res as any).filtered) {
        setMessage({ tone: "error", text: (res as any).message || "This job didn't pass the hard filters (role, sponsorship, or location) and was not queued." });
      } else if ((res as any).deduplicated) {
        setMessage({ tone: "error", text: (res as any).message || "This job is already in the system." });
      } else {
        setMessage({ tone: "success", text: `Queued "${title.trim()}" at ${company.trim()} (${tailoringMode} tailoring). It'll show up below in Ready to Apply.` });
        reset();
        onAdded?.();
      }
    } catch (err: any) {
      setMessage({ tone: "error", text: err?.message || "Failed to queue this job." });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-2xl border border-white/10 bg-[#0a101b] overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-left cursor-pointer hover:bg-white/[0.03] transition-colors"
      >
        <span className="text-xs font-black uppercase tracking-wider text-slate-300 flex items-center gap-2">
          <span className="text-[#2ee8c9] text-base leading-none">+</span>
          Add job by URL
        </span>
        <span className="text-slate-500 text-xs">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="px-5 pb-5 space-y-3 border-t border-white/5 pt-4">
          <p className="text-xs text-slate-400">
            Paste a specific job posting to queue it for Autopilot with a chosen resume-tailoring mode, instead of waiting for the next discovery scrape.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] font-bold uppercase text-slate-500">Company</label>
              <input
                type="text"
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                placeholder="e.g. Stripe"
                className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus:border-cyan-400/50"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] font-bold uppercase text-slate-500">Job Title</label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Senior Software Engineer"
                className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus:border-cyan-400/50"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-bold uppercase text-slate-500">Location (optional)</label>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="e.g. Remote, or San Francisco, CA"
              className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus:border-cyan-400/50"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-bold uppercase text-slate-500">Application URL</label>
            <input
              type="text"
              value={applicationUrl}
              onChange={(e) => setApplicationUrl(e.target.value)}
              placeholder="https://job-boards.greenhouse.io/company/jobs/12345"
              className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus:border-cyan-400/50"
            />
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] font-bold uppercase text-slate-500">Resume Tailoring</label>
              <div className="flex gap-1.5">
                {(["off", "honest", "aggressive"] as TailoringMode[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setTailoringMode(mode)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold capitalize border transition-all cursor-pointer ${
                      tailoringMode === mode
                        ? "bg-[#2ee8c9]/15 border-[#2ee8c9]/50 text-[#2ee8c9]"
                        : "bg-white/5 border-white/10 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={submitting}
              className="px-4 py-2 rounded-xl bg-[#2ee8c9]/15 border border-[#2ee8c9]/40 text-[#2ee8c9] text-xs font-black hover:bg-[#2ee8c9]/25 transition-all cursor-pointer disabled:opacity-40"
            >
              {submitting ? "Queuing..." : "Add to Queue"}
            </button>
          </div>
          {message && (
            <div
              className={`text-xs rounded-lg px-3 py-2 border ${
                message.tone === "success"
                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                  : "bg-rose-500/10 border-rose-500/30 text-rose-300"
              }`}
            >
              {message.text}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
