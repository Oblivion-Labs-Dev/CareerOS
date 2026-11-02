"use client";

import { useEffect, useState } from "react";

const COMMANDS = [
  { id: "create", label: "Create site", hint: "pnpm arsenal create my-site" },
  { id: "theme", label: "Switch theme", hint: "pnpm arsenal theme obsidian-cyber" },
  { id: "preview", label: "Preview", hint: "pnpm arsenal preview" },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-black/60 pt-[20vh] backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-lg rounded-arsenal-lg border border-arsenal-border bg-arsenal-elevated p-2 shadow-arsenal"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          autoFocus
          placeholder="Type a command…"
          className="w-full rounded-arsenal-sm border border-arsenal-border bg-arsenal-surface px-4 py-3 text-sm outline-none focus:border-arsenal-accent"
          data-cursor="input"
        />
        <div className="mt-2">
          {COMMANDS.map((cmd) => (
            <button
              key={cmd.id}
              type="button"
              className="flex w-full items-center justify-between rounded-arsenal-sm px-4 py-2.5 text-left text-sm hover:bg-arsenal-surface"
              data-cursor="button"
            >
              <span>{cmd.label}</span>
              <span className="text-xs text-arsenal-muted">{cmd.hint}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
