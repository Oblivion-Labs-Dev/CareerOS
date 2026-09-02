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
    concurrency: number;
    staggerDelay: number;
    selfHealing: boolean;
    aiModel?: string;
  }) => void;
  initialBatchSize?: number;
  initialAiModel?: string;
  loading?: boolean;
}

const PRESET_SIZES = [1, 5, 10, 15, 30, 50];

export function BatchConfigModal({
  isOpen,
  onClose,
  onStartRun,
  initialBatchSize = 1,
  initialAiModel = "mistral-small3.2:24b",
  loading = false,
}: BatchConfigModalProps) {
  const [batchSize, setBatchSize] = useState<number>(initialBatchSize);
  const [customInput, setCustomInput] = useState<string>("");
  const [isCustom, setIsCustom] = useState<boolean>(false);
  const [aiModel, setAiModel] = useState<string>(initialAiModel);
  const [minMatchScore, setMinMatchScore] = useState<number>(75);
  const [maxPostAgeDays, setMaxPostAgeDays] = useState<number>(7);
  const [sortMode, setSortMode] = useState<string>("highest_match");
  const [concurrency, setConcurrency] = useState<number>(5);
  const [staggerDelay, setStaggerDelay] = useState<number>(0.5);
  const [selfHealingEnabled, setSelfHealingEnabled] = useState<boolean>(true);

  if (!isOpen) return null;

  const handleSubmit = () => {
    const finalCount = isCustom ? parseInt(customInput) || 25 : batchSize;
    onStartRun({
      batchSize: finalCount,
      minMatchScore,
      maxPostAgeDays,
      sortMode,
      concurrency,
      staggerDelay,
      selfHealing: selfHealingEnabled,
      aiModel,
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

        {/* AI Reasoning Engine Selector */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
              AI Reasoning Engine
            </label>
            <span className="text-[10px] text-slate-400">Powers candidate matching & self-healing</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
            <button
              type="button"
              onClick={() => setAiModel("mistral-small")}
              className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                aiModel === "mistral-small"
                  ? "bg-emerald-950/30 border-emerald-500/60 shadow-[0_0_15px_rgba(16,185,129,0.25)] text-white"
                  : "bg-[#060a10] border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-black text-emerald-400">Mistral 24B</span>
                {aiModel === "mistral-small" && <span className="text-[10px] text-emerald-300 font-bold">TOP ACC</span>}
              </div>
              <p className="text-[10px] text-slate-400 mt-1 leading-tight">
                mistral-small:24b. 98% verified accuracy.
              </p>
            </button>

            <button
              type="button"
              onClick={() => setAiModel("gemini")}
              className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                aiModel === "gemini"
                  ? "bg-amber-950/30 border-amber-500/60 shadow-[0_0_15px_rgba(245,158,11,0.25)] text-white"
                  : "bg-[#060a10] border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-black text-amber-400">Gemini Flash</span>
                {aiModel === "gemini" && <span className="text-[10px] text-amber-300 font-bold">GOOGLE</span>}
              </div>
              <p className="text-[10px] text-slate-400 mt-1 leading-tight">
                2.5 Flash. Ultra-fast &amp; multimodal.
              </p>
            </button>

            <button
              type="button"
              onClick={() => setAiModel("gpt-oss")}
              className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                aiModel === "gpt-oss"
                  ? "bg-cyan-950/30 border-cyan-500/60 shadow-[0_0_15px_rgba(34,211,238,0.25)] text-white"
                  : "bg-[#060a10] border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-black text-cyan-400">gpt-oss:20b</span>
                {aiModel === "gpt-oss" && <span className="text-[10px] text-cyan-300 font-bold">LOCAL</span>}
              </div>
              <p className="text-[10px] text-slate-400 mt-1 leading-tight">
                Local Ollama 20B. High accuracy, private.
              </p>
            </button>

            <button
              type="button"
              onClick={() => setAiModel("chatgpt-mini")}
              className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                aiModel === "chatgpt-mini"
                  ? "bg-emerald-950/30 border-emerald-500/60 shadow-[0_0_15px_rgba(16,185,129,0.25)] text-white"
                  : "bg-[#060a10] border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-black text-emerald-400">ChatGPT (4o-mini)</span>
                {aiModel === "chatgpt-mini" && <span className="text-[10px] text-emerald-300 font-bold">OPENAI</span>}
              </div>
              <p className="text-[10px] text-slate-400 mt-1 leading-tight">
                OpenAI API. Fast, 99.8% precision.
              </p>
            </button>
          </div>
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

        {/* Concurrency & Self-Healing Settings */}
        <div className="space-y-3 pt-2 border-t border-white/10">
          <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
            Parallel Workers & Self-Healing
          </label>

          <div className="grid grid-cols-2 gap-4">
            {/* Concurrency Slider */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-slate-300">Concurrent Workers</label>
                <span className="text-xs font-mono text-[#2ee8c9] font-bold">{concurrency}</span>
              </div>
              <input
                type="range"
                min={1}
                max={10}
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
                className="w-full h-1.5 rounded-full appearance-none bg-white/10 accent-[#2ee8c9] cursor-pointer"
              />
              <div className="flex justify-between text-[9px] text-slate-500">
                <span>1 (Sequential)</span>
                <span>5 (Balanced)</span>
                <span>10 (Max)</span>
              </div>
            </div>

            {/* Stagger Delay */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">Stagger Delay</label>
              <select
                value={staggerDelay}
                onChange={(e) => setStaggerDelay(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-xl bg-[#060a10] border border-white/15 text-slate-200 text-xs focus:outline-none focus:border-[#2ee8c9]"
              >
                <option value={0.5}>0.5s (Recommended)</option>
                <option value={1}>1s (Conservative)</option>
                <option value={2}>2s (Slow / rate-limit recovery)</option>
              </select>
            </div>
          </div>

          {/* Self-Healing Toggle */}
          <div className="flex items-center justify-between p-3 rounded-xl bg-[#060a10] border border-white/10">
            <div>
              <div className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                🔧 Self-Healing Code Fix
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">
                After each batch, Qwen analyzes failures and auto-patches the executor code
              </div>
            </div>
            <button
              type="button"
              onClick={() => setSelfHealingEnabled(!selfHealingEnabled)}
              className={`relative w-10 h-5 rounded-full transition-colors cursor-pointer ${
                selfHealingEnabled ? "bg-[#2ee8c9]" : "bg-white/20"
              }`}
            >
              <span
                className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                  selfHealingEnabled ? "translate-x-5" : "translate-x-0.5"
                }`}
              />
            </button>
          </div>
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
