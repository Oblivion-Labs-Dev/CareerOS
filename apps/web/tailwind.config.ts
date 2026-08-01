/** Tailwind preset inlined for PostCSS/Turbopack compatibility in CareerOS. */
const arsenalPreset = {
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#58dec4",
          strong: "#3cbfa8",
          soft: "rgba(88, 222, 196, 0.12)",
        },
        arsenal: {
          background: "var(--arsenal-background)",
          surface: "var(--arsenal-surface)",
          elevated: "var(--arsenal-elevated)",
          border: "var(--arsenal-border)",
          primary: "var(--arsenal-text-primary)",
          secondary: "var(--arsenal-text-secondary)",
          muted: "var(--arsenal-muted)",
          accent: "var(--arsenal-accent)",
          danger: "var(--arsenal-danger)",
          success: "var(--arsenal-success)",
        },
      },
      borderRadius: {
        arsenal: "var(--arsenal-radius)",
        "arsenal-sm": "var(--arsenal-radius-sm)",
        "arsenal-lg": "var(--arsenal-radius-lg)",
      },
      boxShadow: {
        arsenal: "0 8px 32px rgba(0,0,0,0.35)",
        "arsenal-glow": "0 0 48px color-mix(in srgb, var(--arsenal-accent) 35%, transparent)",
      },
    },
  },
};

/** @type {import('tailwindcss').Config} */
export default {
  presets: [arsenalPreset],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./node_modules/@arsenal/ui/dist/**/*.js",
    "../../packages/career-ui/src/**/*.{ts,tsx}",
  ],
  corePlugins: {
    preflight: false,
  },
};
