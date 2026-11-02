"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export function ThemeMorphButton() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div className="w-9 h-9 rounded-xl border border-white/10 bg-white/5" />
    );
  }

  const isLight = (resolvedTheme ?? theme) === "light";

  return (
    <button
      type="button"
      onClick={() => setTheme(isLight ? "dark" : "light")}
      className={`relative flex items-center justify-center w-9 h-9 rounded-xl border transition-all duration-300 cursor-pointer overflow-hidden group active:scale-95 ${
        isLight
          ? "bg-amber-500/10 border-amber-500/30 text-amber-600 hover:bg-amber-500/20 hover:border-amber-500/50 shadow-[0_0_15px_rgba(245,158,11,0.2)]"
          : "bg-[#2ee8c9]/10 border-[#2ee8c9]/30 text-[#2ee8c9] hover:bg-[#2ee8c9]/20 hover:border-[#2ee8c9]/50 shadow-[0_0_15px_rgba(46,232,201,0.25)]"
      }`}
      aria-label={isLight ? "Switch to Dark Mode" : "Switch to Light Mode"}
      title={isLight ? "Switch to Dark Mode" : "Switch to Light Mode"}
    >
      {/* Sun / Moon Morphing Icon */}
      <div className="relative w-4 h-4 transition-transform duration-500 group-hover:rotate-12">
        {/* Sun Icon */}
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`w-4 h-4 absolute inset-0 transition-all duration-500 ${
            isLight
              ? "opacity-100 rotate-0 scale-100 text-amber-500"
              : "opacity-0 -rotate-90 scale-50 pointer-events-none"
          }`}
        >
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2" />
          <path d="M12 20v2" />
          <path d="m4.93 4.93 1.41 1.41" />
          <path d="m17.66 17.66 1.41 1.41" />
          <path d="M2 12h2" />
          <path d="M20 12h2" />
          <path d="m6.34 17.66-1.41 1.41" />
          <path d="m19.07 4.93-1.41 1.41" />
        </svg>

        {/* Moon Icon */}
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`w-4 h-4 absolute inset-0 transition-all duration-500 ${
            !isLight
              ? "opacity-100 rotate-0 scale-100 text-[#2ee8c9]"
              : "opacity-0 rotate-90 scale-50 pointer-events-none"
          }`}
        >
          <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
          <path d="M19 3v4" />
          <path d="M21 5h-4" />
        </svg>
      </div>

      {/* Subtle Glow Ring on Hover */}
      <span
        className={`absolute inset-0 rounded-xl transition-opacity duration-300 opacity-0 group-hover:opacity-100 pointer-events-none ${
          isLight ? "bg-amber-400/10" : "bg-[#2ee8c9]/10"
        }`}
      />
    </button>
  );
}
