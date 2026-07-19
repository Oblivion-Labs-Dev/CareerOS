"use client";

import React, { useState } from "react";
import { Accomplishment } from "../types";

interface MetricsTabProps {
  accomplishments: Accomplishment[];
}

export function MetricsTab({ accomplishments }: MetricsTabProps) {
  const [selectedMetricType, setSelectedMetricType] = useState<string>("all");

  // Compile metrics list
  const metricsList: { metric: string; value: string; project: string; company: string; category: string }[] = [];
  accomplishments.forEach((acc) => {
    acc.scaleMetrics?.forEach((m) => {
      let cat = "scale";
      if (m.metric.toLowerCase().includes("saving") || m.metric.toLowerCase().includes("$") || m.metric.toLowerCase().includes("cost")) {
        cat = "business";
      } else if (m.metric.toLowerCase().includes("latency") || m.metric.toLowerCase().includes("tps") || m.metric.toLowerCase().includes("qps")) {
        cat = "performance";
      }
      metricsList.push({
        metric: m.metric,
        value: m.value,
        project: acc.project,
        company: acc.company,
        category: cat,
      });
    });
  });

  const filteredMetrics = selectedMetricType === "all"
    ? metricsList
    : metricsList.filter(m => m.category === selectedMetricType);

  // Compute SVG chart data based on counts
  const businessCount = metricsList.filter(m => m.category === "business").length;
  const performanceCount = metricsList.filter(m => m.category === "performance").length;
  const scaleCount = metricsList.filter(m => m.category === "scale").length;
  
  const total = businessCount + performanceCount + scaleCount || 1;
  const pBusiness = Math.round((businessCount / total) * 100);
  const pPerformance = Math.round((performanceCount / total) * 100);
  const pScale = Math.round((scaleCount / total) * 100);

  return (
    <div className="flex flex-col gap-8 animate-fade-in text-slate-100">
      <div className="flex justify-between items-center border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Structured Metrics System</h3>
          <p className="text-xs text-slate-500 mt-0.5">Metrics are parsed into individual metadata objects for automated resume generation.</p>
        </div>
        <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-md border border-slate-800/80">
          {[
            { id: "all", label: "All Metrics" },
            { id: "business", label: "Business Value" },
            { id: "performance", label: "Performance" },
            { id: "scale", label: "Scale" },
          ].map((type) => (
            <button
              key={type.id}
              onClick={() => setSelectedMetricType(type.id)}
              className={`px-2.5 py-1 rounded text-[10px] font-bold capitalize transition ${
                selectedMetricType === type.id
                  ? "bg-slate-800 text-violet-400"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {type.label}
            </button>
          ))}
        </div>
      </div>

      {/* SVG Interactive Chart Component */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-center">
        <div className="md:col-span-1 p-6 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-3 justify-center items-center text-center">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Metrics Distribution</span>
          
          <div className="relative w-32 h-32 mt-2">
            <svg className="w-full h-full transform -rotate-90" viewBox="0 0 36 36">
              {/* Scale category ring */}
              <circle
                className="stroke-slate-800"
                strokeWidth="4"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              <circle
                className="stroke-violet-500"
                strokeDasharray={`${pScale}, 100`}
                strokeWidth="4"
                strokeLinecap="round"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              {/* Performance category ring */}
              <circle
                className="stroke-emerald-500"
                strokeDasharray={`${pPerformance}, 100`}
                strokeDashoffset={`-${pScale}`}
                strokeWidth="4"
                strokeLinecap="round"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              {/* Business value ring */}
              <circle
                className="stroke-blue-500"
                strokeDasharray={`${pBusiness}, 100`}
                strokeDashoffset={`-${pScale + pPerformance}`}
                strokeWidth="4"
                strokeLinecap="round"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center text-xs font-bold text-white">
              <span>{metricsList.length}</span>
              <span className="text-[9px] text-slate-500 uppercase tracking-widest font-semibold">Metrics</span>
            </div>
          </div>

          <div className="flex flex-wrap gap-3 mt-4 text-[9px] font-semibold">
            <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded bg-violet-500"></span><span className="text-slate-300">Scale ({pScale}%)</span></div>
            <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded bg-emerald-500"></span><span className="text-slate-300">Performance ({pPerformance}%)</span></div>
            <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded bg-blue-500"></span><span className="text-slate-300">Business ({pBusiness}%)</span></div>
          </div>
        </div>

        {/* Metrics breakdown items */}
        <div className="md:col-span-2 flex flex-col gap-3">
          {filteredMetrics.length === 0 ? (
            <div className="text-xs text-slate-500 italic py-6 text-center border border-slate-800 border-dashed rounded-lg">
              No matching metric objects found. Try recording more accomplishments with specific numeric data.
            </div>
          ) : (
            filteredMetrics.map((item, idx) => (
              <div
                key={idx}
                className="p-4 rounded-lg bg-slate-950 border border-slate-850 hover:border-slate-800 transition flex justify-between items-center text-xs"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`w-1.5 h-1.5 rounded-full ${
                      item.category === "business" ? "bg-blue-500" : item.category === "performance" ? "bg-emerald-500" : "bg-violet-500"
                    }`}></span>
                    <span className="font-bold text-slate-200">{item.metric}</span>
                  </div>
                  <span className="text-[10px] text-slate-500 mt-1 block font-semibold">{item.project} ({item.company})</span>
                </div>
                <span className={`font-black text-sm px-2 py-0.5 rounded ${
                  item.category === "business" ? "text-blue-400" : item.category === "performance" ? "text-emerald-400" : "text-violet-400"
                }`}>
                  {item.value}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
