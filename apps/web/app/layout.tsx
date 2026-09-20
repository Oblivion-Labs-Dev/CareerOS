import type { Metadata } from "next";
import { Geist, Instrument_Serif, Inter, JetBrains_Mono, Outfit } from "next/font/google";
import { AppProviders } from "@/components/providers/app-providers";
import "./globals.css";
import "./career-system.css";
import "./cos-design-system.css";
import "./cos-refine.css";
import "./product-polish.css";
import "./reference-match.css";
import "./cos-light-mode.css";
// Last: re-expresses the global classes the 37 pages already use in the shared
// token language, so the whole app inherits one design language at once.
import "./design-language.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const outfit = Outfit({
  subsets: ["latin"],
  variable: "--font-outfit",
  display: "swap",
});

/**
 * The Editorial precision stack.
 *
 * Three faces, each with one job, because the previous single-face setup
 * (Inter for everything) gave the interface no voice and no way to signal
 * hierarchy except size.
 *
 * - Geist carries body and UI text. Neutral like Inter but drawn tighter, so
 *   dense tables read better at small sizes.
 * - Instrument Serif carries display headings only. This is where the
 *   personality lives; used sparingly it reads as considered rather than
 *   decorative.
 * - JetBrains Mono carries figures. This product is numbers-dense — counts,
 *   percentages, match scores, countdowns — and it has real tabular numerals,
 *   so digits stop shifting width as values animate.
 *
 * Inter stays loaded: 37 pages still reference --font-inter, and swapping that
 * out underneath them is a separate change from introducing the new stack.
 */
const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist",
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-display",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-figure",
  display: "swap",
});

export const metadata: Metadata = {
  title: "CareerOS — AI Career Operating System",
  description: "AI-powered career operating system. ApplyPilot autofill, application tracking, and career intelligence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${outfit.variable} ${geist.variable} ${instrumentSerif.variable} ${jetbrainsMono.variable}`}
    >
      <body className={geist.className}>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
