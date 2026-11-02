import { getClientApiBaseUrl } from "@/lib/api";

export interface NetworkingContact {
  id: string;
  contactName: string;
  email?: string;
  linkedin?: string;
  companyName?: string;
  roleTitle?: string;
  phone?: string;
  relationship?: string;
  status?: "active" | "asked" | "referred" | "inactive";
  notes?: string;
  source?: string;
}

export interface NetworkingApplication {
  id: string;
  companyName?: string;
  roleTitle?: string;
  status?: string;
  jobUrl?: string;
  createdAt?: string;
}

export interface NetworkingDiscoveredJob {
  id: string;
  title?: string;
  company?: string;
  location?: string;
  applicationUrl?: string;
  active?: boolean;
}

export interface CompanyWorkspace {
  success: boolean;
  companyName: string;
  applications: NetworkingApplication[];
  discoveredJobs: NetworkingDiscoveredJob[];
  contacts: NetworkingContact[];
}

export interface OutreachDraft {
  emailSubject: string;
  emailBody: string;
  linkedinNote: string;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getClientApiBaseUrl()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = `Request failed: ${path}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // ignore parse failure, keep default message
    }
    throw new Error(detail);
  }
  return res.json();
}

export function listNetworkingCompanies() {
  return apiFetch<{ success: boolean; companies: string[] }>("/networking/companies");
}

export function getCompanyWorkspace(companyName: string) {
  return apiFetch<CompanyWorkspace>(`/networking/company/${encodeURIComponent(companyName)}`);
}

export function addCompanyContact(
  companyName: string,
  contact: {
    contactName: string;
    roleTitle?: string;
    email?: string;
    linkedin?: string;
    relationship?: string;
    notes?: string;
  },
) {
  return apiFetch<{ success: boolean; contact: NetworkingContact }>(
    `/networking/company/${encodeURIComponent(companyName)}/contacts`,
    { method: "POST", body: JSON.stringify(contact) },
  );
}

export function draftOutreach(input: {
  contactName: string;
  contactRole?: string;
  companyName: string;
  jobId?: string;
}) {
  return apiFetch<{ success: boolean; draft: OutreachDraft }>("/networking/draft-outreach", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
