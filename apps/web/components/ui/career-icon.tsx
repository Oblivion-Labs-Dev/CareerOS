import type { SVGProps } from "react";

export interface CareerIconProps extends Omit<SVGProps<SVGSVGElement>, "ref"> {
  name: string;
  size?: number;
}

export function CareerIcon({ name, size = 18, ...props }: CareerIconProps) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
    ...props,
  };

  switch (name) {
    case "today":
      return <svg {...common}><path d="M4 5.5h16v14H4z"/><path d="M8 3.5v4M16 3.5v4M4 9.5h16"/><path d="m8 14 2 2 5-5"/></svg>;
    case "profile":
      return <svg {...common}><circle cx="12" cy="8" r="3.25"/><path d="M5.5 20c.65-4 2.8-6 6.5-6s5.85 2 6.5 6"/></svg>;
    case "documents":
      return <svg {...common}><path d="M6 3.5h8l4 4V20H6z"/><path d="M14 3.5v4h4M9 12h6M9 16h5"/></svg>;
    case "evidence":
      return <svg {...common}><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h5M8 16h3"/><path d="m15 15 1.3 1.3L19 13.5"/></svg>;
    case "jobs":
      return <svg {...common}><rect x="3.5" y="7" width="17" height="12" rx="2"/><path d="M9 7V5h6v2M3.5 12h17M10 12v2h4v-2"/></svg>;
    case "applications":
      return <svg {...common}><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h4"/><circle cx="17" cy="17" r="3.25"/><path d="m15.7 17 1 1 1.8-2"/></svg>;
    case "relationships":
      return <svg {...common}><circle cx="8" cy="8" r="3"/><circle cx="17" cy="7" r="2.25"/><path d="M3.5 20c.4-4 1.9-6 4.5-6s4.1 2 4.5 6M14 13c3.6-.2 5.6 1.8 6 5"/></svg>;
    case "interviews":
      return <svg {...common}><path d="M4 5.5h16v11H9l-4 3v-3H4z"/><path d="M8 9h8M8 13h5"/></svg>;
    case "insights":
      return <svg {...common}><path d="M4 19.5V11M10 19.5V5M16 19.5v-8M22 19.5H2"/><path d="m4 8 5-4 6 4 5-5"/></svg>;
    case "applypilot":
      return <svg {...common}><path d="m12 3 2.15 4.85L19 10l-4.85 2.15L12 17l-2.15-4.85L5 10l4.85-2.15z"/><path d="m18.5 16 .9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z"/></svg>;
    case "resources":
      return <svg {...common}><path d="M4 5.5A3.5 3.5 0 0 1 7.5 2H20v16H7.5A3.5 3.5 0 0 0 4 21.5z"/><path d="M4 5.5V22M8 6h8M8 10h6"/></svg>;
    case "settings":
      return <svg {...common}><circle cx="12" cy="12" r="3"/><path d="M18.5 13.5v-3l-2-.6a7 7 0 0 0-.8-1.9l1-1.8-2.1-2.1-1.8 1a7 7 0 0 0-1.9-.8L9.3 2h-3l-.6 2.3a7 7 0 0 0-1.9.8l-1.8-1-.6.6M5.5 19.7l.2-1.2" transform="translate(2.2) scale(.82)"/></svg>;
    case "roadmap":
      return <svg {...common}><circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M8 18h2.5A3.5 3.5 0 0 0 14 14.5v-5A3.5 3.5 0 0 1 17.5 6M7.5 6H3v5M3 6l4 4"/></svg>;
    case "search":
      return <svg {...common}><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/></svg>;
    case "arrow":
      return <svg {...common}><path d="M5 12h14M14 7l5 5-5 5"/></svg>;
    case "spark":
      return <svg {...common}><path d="m12 2 1.7 5.3L19 9l-5.3 1.7L12 16l-1.7-5.3L5 9l5.3-1.7zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>;
    case "close":
      return <svg {...common}><path d="m6 6 12 12M18 6 6 18"/></svg>;
    case "menu":
      return <svg {...common}><path d="M4 7h16M4 12h16M4 17h16"/></svg>;
    case "external":
      return <svg {...common}><path d="M14 5h5v5M19 5l-8 8"/><path d="M17 13v6H5V7h6"/></svg>;
    case "clock":
      return <svg {...common}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>;
    case "check":
      return <svg {...common}><path d="m5 12 4 4L19 6"/></svg>;
    default:
      return <svg {...common}><circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/></svg>;
  }
}

