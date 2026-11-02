import { getClientApiBaseUrl, postJson } from "./api";

export type MemoryNote = {
  id: string;
  text: string;
  source: "user" | "auto";
  createdAt?: string;
};

export type PortfolioSettings = {
  isPublic: boolean;
  slug: string;
};

export type PublicPortfolio = {
  name: string;
  headline: string;
  location: string;
  yearsExperience: number | string | null;
  skills: string[];
  accomplishments: { company: string; project: string; summary: string }[];
  experience: { company: string; title: string; startDate: string; endDate: string }[];
};

export type JobBoard = { id: string; name: string; connected: boolean };

export async function listMemoryNotes(): Promise<MemoryNote[]> {
  const res = await fetch(`${getClientApiBaseUrl()}/settings/memory`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load memory notes");
  const data = (await res.json()) as { notes: MemoryNote[] };
  return data.notes ?? [];
}

export async function addMemoryNote(text: string): Promise<MemoryNote> {
  const data = await postJson<{ note: MemoryNote }>("/settings/memory", { text });
  return data.note;
}

export async function deleteMemoryNote(id: string): Promise<void> {
  await postJson(`/settings/memory/${encodeURIComponent(id)}`, {}, "DELETE");
}

export async function getPortfolioSettings(): Promise<PortfolioSettings> {
  const res = await fetch(`${getClientApiBaseUrl()}/settings/portfolio`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load portfolio settings");
  const data = (await res.json()) as { settings: PortfolioSettings };
  return data.settings;
}

export async function savePortfolioSettings(patch: Partial<PortfolioSettings>): Promise<PortfolioSettings> {
  const data = await postJson<{ settings: PortfolioSettings }>("/settings/portfolio", patch, "PATCH");
  return data.settings;
}

export async function listJobBoards(): Promise<JobBoard[]> {
  const res = await fetch(`${getClientApiBaseUrl()}/settings/job-boards`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load job boards");
  const data = (await res.json()) as { boards: JobBoard[] };
  return data.boards ?? [];
}

export async function fetchPublicPortfolio(slug: string): Promise<PublicPortfolio | null> {
  const res = await fetch(`${getClientApiBaseUrl()}/public/portfolio/${encodeURIComponent(slug)}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Failed to load portfolio");
  const data = (await res.json()) as { portfolio: PublicPortfolio };
  return data.portfolio;
}
