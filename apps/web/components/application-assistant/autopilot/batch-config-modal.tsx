"use client";

import React, { useState } from "react";
import { IconPlay, IconSettings } from "./icons";

interface BatchConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  onStartRun: (config: {
    batchSize: number;
    minMatchScore: number;
    maxPostAgeDays: number;
    sortMode: string;
  }) => void;
  initialBatchSize?: number;
  loading?: boolean;
}

const PRESET_SIZES = [5, 10, 25, 50, 100];

export function BatchConfigModal({
  isOpen,
  onClose,
  onStartRun,
  initialBatchSize = 25,
  loading = false,
}: BatchConfigModalProps) {
  const [batchSize, setBatchSize] = useState<number>(initialBatchSize);
  const [customInput, setCustomInput] = useState<string>("");
  const [isCustom, setIsCustom] = useState<boolean>(false);
  const [minMatchScore, setMinMatchScore] = useState<number>(75);
  const [maxPostAgeDays, setMaxPostAgeDays] = useState<number>(7);
  const [sortMode, setSortMode] = useState<string>("highest_match");

  if (!isOpen) return null;

  const handleSubmit = () => {
    const finalCount = isCustom ? parseInt(customInput) || 25 : batchSize;
    onStartRun({
      batchSize: finalCount,
      minMatchScore,
      maxPostAgeDays,
      sortMode,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
      <div className="w-full max-w-lg rounded-2xl border border-white/15 bg-gradient-to-b from-[#0e1622] to-[#080d16] p-6 shadow-2xl space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-[#2ee8c9]/15 border border-[#2ee8c9]/30 flex items-center justify-center text-[#2ee8c9]">
              <IconSettings className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Run Configuration</h3>
              <p className="text-xs text-slate-400">Configure parameters for the next Autopilot batch run</p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white flex items-center justify-center cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Batch Size Selector */}
        <div className="space-y-2">
          <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
            Target Batch Size (Applications)
          </label>
          <div className="flex flex-wrap items-center gap-2">
            {PRESET_SIZES.map((size) => (
              <button
                key={size}
                type="button"
                onClick={() => {
                  setBatchSize(size);
                  setIsCustom(false);
                }}
                className={`px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                  !isCustom && batchSize === size
                    ? "bg-[#2ee8c9]/20 border border-[#2ee8c9]/50 text-[#2ee8c9] shadow-[0_0_15px_rgba(46,232,201,0.3)]"
                    : "bg-[#060b12] border border-white/10 text-slate-400 hover:text-white hover:border-white/20"
                }`}
              >
                {size}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setIsCustom(true)}
              className={`px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                isCustom
                  ? "bg-[#2ee8c9]/20 border border-[#2ee8c9]/50 text-[#2ee8c9] shadow-[0_0_15px_rgba(46,232,201,0.3)]"
                  : "bg-[#060b12] border border-white/10 text-slate-400 hover:text-white hover:border-white/20"
              }`}
            >
              Custom
            </button>
          </div>

          {isCustom && (
            <div className="pt-2">
              <input
                type="number"
                min="1"
                max="500"
                placeholder="Enter custom count (1-500)..."
                value={customInput}
                onChange={(e) => setCustomInput(e.target.value)}
                className="w-full px-4 py-2 rounded-xl bg-[#060a10] border border-white/15 text-white text-xs focus:outline-none focus:border-[#2ee8c9]"
              />
            </div>
          )}
        </div>

        {/* Quality Controls */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-300">Min Match Score</label>
            <select
              value={minMatchScore}
              onChange={(e) => setMinMatchScore(Number(e.target.value))}
              className="w-full px-3 py-2 rounded-xl bg-[#060a10] border border-white/15 text-slate-200 text-xs focus:outline-none focus:border-[#2ee8c9]"
            >
              <option value={85}>85% + (Strict)</option>
              <option value={75}>75% + (Standard Recommended)</option>
              <option value={60}>60% + (Broad)</option>
              <option value={0}>0% (All Jobs / Demo)</option>
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-300">Max Posting Age</label>
            <select
              value={maxPostAgeDays}
              onChange={(e) => setMaxPostAgeDays(Number(e.target.value))}
              className="w-full px-3 py-2 rounded-xl bg-[#060a10] border border-white/15 text-slate-200 text-xs focus:outline-none focus:border-[#2ee8c9]"
            >
              <option value={3}>Last 3 days</option>
              <option value={7}>Last 7 days (Recommended)</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
            </select>
          </div>
        </div>

        {/* Queue Sort Mode */}
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-slate-300">Queue Processing Order</label>
          <select
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value)}
            className="w-full px-3 py-2 rounded-xl bg-[#060a10] border border-white/15 text-slate-200 text-xs focus:outline-none focus:border-[#2ee8c9]"
          >
            <option value="highest_match">Highest Match First (Recommended)</option>
            <option value="newest_first">Newest Postings First</option>
            <option value="target_companies">Target Companies Priority</option>
          </select>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/10">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-xs font-semibold cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading}
            className="px-5 py-2 rounded-xl bg-gradient-to-r from-[#2ee8c9] to-[#38bdf8] hover:from-[#26cfb3] hover:to-[#2fa8dc] text-[#05110d] font-extrabold text-xs shadow-[0_0_20px_rgba(46,232,201,0.4)] transition-all cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
          >
            <IconPlay className="w-3.5 h-3.5" />
            {loading ? "Starting..." : "Start Autopilot Run"}
          </button>
        </div>
      </div>
    </div>
  );
}
