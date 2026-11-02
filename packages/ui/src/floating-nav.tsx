"use client";

import { cn } from "./lib/cn";

export function FloatingNav({ className }: { className?: string }) {
  const links = [
    { label: "Features", href: "#features" },
    { label: "Templates", href: "#templates" },
    { label: "Themes", href: "#themes" },
    { label: "Modules", href: "#modules" },
    { label: "Context", href: "/context" },
  ];
  return (
    <nav
      className={cn(
        "fixed left-1/2 top-6 z-50 flex -translate-x-1/2 items-center gap-1 rounded-full",
        "border border-arsenal-border bg-arsenal-surface/70 px-2 py-2 backdrop-blur-xl",
        className,
      )}
    >
      <a href="/" className="px-3 text-sm font-semibold text-arsenal-accent">
        Arsenal
      </a>
      {links.map((link) => (
        <a
          key={link.label}
          href={link.href}
          className="rounded-full px-3 py-1.5 text-sm text-arsenal-secondary transition hover:bg-arsenal-elevated hover:text-arsenal-primary"
          data-cursor="link"
        >
          {link.label}
        </a>
      ))}
    </nav>
  );
}
