import type { Metadata } from "next";
import { Inter, Outfit } from "next/font/google";
import { AppProviders } from "@/components/providers/app-providers";
import "./globals.css";
import "./career-system.css";
import "./cos-design-system.css";
import "./cos-refine.css";
import "./product-polish.css";
import "./reference-match.css";
import "./cos-light-mode.css";

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

export const metadata: Metadata = {
  title: "CareerOS — AI Career Operating System",
  description: "AI-powered career operating system. ApplyPilot autofill, application tracking, and career intelligence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${outfit.variable}`}>
      <body className={inter.className}>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
