"use client";

import React, { useState, useEffect, useRef } from "react";
import { Accomplishment } from "./types";

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  accomplishments: Accomplishment[];
  onNavigate: (tab: string) => void;
  onSelectAccomplishment: (acc: Accomplishment) => void;
  onCreateNew: () => void;
}

export function CommandPalette({
  isOpen,
  onClose,
  accomplishments,
  onNavigate,
  onSelectAccomplishment,
  onCreateNew,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Handle Global Hotkey
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // Keyboard navigation inside list
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => Math.min(prev + 1, filteredItems.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => Math.max(prev - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filteredItems[selectedIndex]) {
        handleSelect(filteredItems[selectedIndex]);
      }
    }
  };

  // Scroll active item into view
  useEffect(() => {
    const activeEl = resultsRef.current?.children[selectedIndex] as HTMLElement;
    if (activeEl) {
      activeEl.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  // Compile command items
  const navigationItems = [
    { type: "nav", id: "overview", label: "Navigate to Overview Dashboard", category: "Navigation", shortcut: "G O" },
    { type: "nav", id: "accomplishments", label: "Navigate to Accomplishments Explorer", category: "Navigation", shortcut: "G A" },
    { type: "nav", id: "builder", label: "Navigate to Resume Builder Canvas", category: "Navigation", shortcut: "G B" },
    { type: "nav", id: "match", label: "Navigate to Job Match Analyzer", category: "Navigation", shortcut: "G M" },
    { type: "nav", id: "interview", label: "Navigate to Interview Prep", category: "Navigation", shortcut: "G I" },
    { type: "nav", id: "metrics", label: "Navigate to Metrics System", category: "Navigation", shortcut: "G N" },
    { type: "nav", id: "skills", label: "Navigate to Skills Intelligence", category: "Navigation", shortcut: "G S" },
    { type: "nav", id: "graph", label: "Navigate to Knowledge Graph View", category: "Navigation", shortcut: "G G" },
    { type: "nav", id: "evidence", label: "Navigate to Evidence Files", category: "Navigation", shortcut: "G E" },
    { type: "nav", id: "reviews", label: "Navigate to Reviewer Intelligence", category: "Navigation", shortcut: "G R" },
  ];

  const actionItems = [
    { type: "action", id: "create", label: "Record New Engineering Accomplishment", category: "Actions", shortcut: "N" },
  ];

  const accItems = accomplishments.map((acc) => ({
    type: "accomplishment",
    id: acc.id,
    label: `${acc.project} at ${acc.company}`,
    category: "Accomplishments",
    data: acc,
    shortcut: ""
  }));

  const allItems = [...actionItems, ...navigationItems, ...accItems];

  const filteredItems = allItems.filter((item) =>
    item.label.toLowerCase().includes(query.toLowerCase()) ||
    item.category.toLowerCase().includes(query.toLowerCase())
  );

  const handleSelect = (item: typeof allItems[0]) => {
    if (item.type === "nav") {
      onNavigate(item.id);
    } else if (item.type === "action") {
      if (item.id === "create") onCreateNew();
    } else if (item.type === "accomplishment") {
      onSelectAccomplishment((item as any).data);
    }
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] px-4 bg-black/75 backdrop-blur-sm">
      <div className="w-full max-w-xl bg-slate-900 border border-slate-800/80 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[500px]">
        {/* Search Input bar */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-slate-800 bg-slate-950/20">
          <span className="text-slate-400 text-sm">🔍</span>
          <input
            ref={inputRef}
            type="text"
            placeholder="Type a command or search accomplishments..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
            className="w-full bg-transparent border-none text-slate-200 placeholder-slate-500 text-sm focus:outline-none focus:ring-0"
          />
          <kbd className="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded border border-slate-700 font-mono shadow-sm">ESC</kbd>
        </div>

        {/* Results list */}
        <div ref={resultsRef} className="overflow-y-auto p-2 flex flex-col gap-0.5">
          {filteredItems.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-500 italic">
              No matching commands or accomplishments found.
            </div>
          ) : (
            filteredItems.map((item, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <button
                  key={`${item.type}-${item.id}`}
                  onClick={() => handleSelect(item)}
                  className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-left transition text-xs ${
                    isSelected
                      ? "bg-violet-600/90 text-white"
                      : "text-slate-300 hover:bg-slate-800/40 hover:text-slate-100"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded tracking-wide border uppercase ${
                      isSelected
                        ? "bg-violet-700 border-violet-500 text-white"
                        : "bg-slate-800 border-slate-700 text-slate-400"
                    }`}>
                      {item.category}
                    </span>
                    <span className="font-medium truncate max-w-[320px]">{item.label}</span>
                  </div>

                  {item.shortcut && (
                    <kbd className={`text-[9px] font-mono px-1.5 py-0.5 rounded border shadow-sm ${
                      isSelected
                        ? "bg-violet-700 border-violet-500 text-violet-100"
                        : "bg-slate-950 border-slate-800 text-slate-500"
                    }`}>
                      {item.shortcut}
                    </kbd>
                  )}
                </button>
              );
            })
          )}
        </div>

        {/* Command palette Footer */}
        <div className="flex items-center justify-between px-4 py-2 border-t border-slate-800/50 bg-slate-950/40 text-[10px] text-slate-500 font-medium">
          <div className="flex items-center gap-3">
            <span>↑↓ Navigate</span>
            <span>↵ Select</span>
          </div>
          <span>Press <kbd className="font-mono">Esc</kbd> to exit</span>
        </div>
      </div>
    </div>
  );
}
