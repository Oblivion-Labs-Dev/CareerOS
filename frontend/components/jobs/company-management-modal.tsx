"use client";

import { useState, useEffect } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

type CompanyItem = {
  company: string;
  source: string;
  config: Record<string, any>;
  enabled: boolean;
};

export function CompanyManagementModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const [companies, setCompanies] = useState<CompanyItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [companyName, setCompanyName] = useState("");
  const [careersUrl, setCareersUrl] = useState("");
  const [selectedSource, setSelectedSource] = useState("auto");
  const [discoveryStatus, setDiscoveryStatus] = useState<string | null>(null);

  const fetchCompanies = async () => {
    setLoading(true);
    try {
      const baseUrl = getClientApiBaseUrl();
      const res = await fetch(`${baseUrl}/api/jobs/companies`);
      const data = await res.json();
      if (data.success) {
        setCompanies(data.companies || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchCompanies();
    }
  }, [isOpen]);

  const handleAddCompany = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!companyName) return;

    const baseUrl = getClientApiBaseUrl();
    let finalSource = selectedSource;
    let finalConfig: Record<string, any> = { careersUrl };

    if (selectedSource === "auto" && careersUrl) {
      setDiscoveryStatus("Detecting source...");
      try {
        const discRes = await fetch(`${baseUrl}/api/jobs/companies/discover`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ company: companyName, careersUrl }),
        });
        const discData = await discRes.json();
        if (discData.success) {
          finalSource = discData.detectedSource;
          finalConfig = { ...finalConfig, ...discData.sourceConfig };
          setDiscoveryStatus(`Detected ${discData.detectedSource} (${Math.round(discData.confidence * 100)}% confidence)`);
        }
      } catch (err) {
        setDiscoveryStatus("Auto-discovery failed, saving as generic");
      }
    }

    try {
      await fetch(`${baseUrl}/api/jobs/companies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company: companyName,
          source: finalSource,
          careersUrl,
          config: finalConfig,
        }),
      });
      setCompanyName("");
      setCareersUrl("");
      setSelectedSource("auto");
      fetchCompanies();
    } catch (err) {
      console.error(err);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 text-slate-100 rounded-xl max-w-2xl w-full p-6 shadow-2xl space-y-6">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div>
            <h3 className="text-lg font-semibold text-white">Target Companies Registry</h3>
            <p className="text-xs text-slate-400">Manage tracked technology companies & ATS sources</p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-xl font-medium px-2 py-1 rounded-md"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleAddCompany} className="grid grid-cols-1 sm:grid-cols-4 gap-3 bg-slate-950 p-4 rounded-lg border border-slate-800">
          <input
            type="text"
            placeholder="Company Name (e.g. Stripe)"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            className="bg-slate-900 border border-slate-700 text-xs text-white rounded-md px-3 py-2 focus:outline-none focus:border-indigo-500"
            required
          />
          <input
            type="url"
            placeholder="Careers URL"
            value={careersUrl}
            onChange={(e) => setCareersUrl(e.target.value)}
            className="bg-slate-900 border border-slate-700 text-xs text-white rounded-md px-3 py-2 focus:outline-none focus:border-indigo-500 sm:col-span-2"
          />
          <select
            value={selectedSource}
            onChange={(e) => setSelectedSource(e.target.value)}
            className="bg-slate-900 border border-slate-700 text-xs text-white rounded-md px-3 py-2 focus:outline-none focus:border-indigo-500"
          >
            <option value="auto">Auto Detect</option>
            <option value="greenhouse">Greenhouse</option>
            <option value="lever">Lever</option>
            <option value="ashby">Ashby</option>
            <option value="workday">Workday</option>
            <option value="generic">Generic HTML</option>
          </select>
          <div className="sm:col-span-4 flex items-center justify-between pt-1">
            <span className="text-xs text-indigo-400 italic">{discoveryStatus}</span>
            <button
              type="submit"
              className="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium px-4 py-2 rounded-md transition-colors"
            >
              Add Company
            </button>
          </div>
        </form>

        <div className="max-h-64 overflow-y-auto space-y-2 pr-1">
          {loading ? (
            <p className="text-xs text-slate-400 text-center py-4">Loading registry...</p>
          ) : companies.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-4">No companies registered yet.</p>
          ) : (
            companies.map((c, idx) => (
              <div key={idx} className="flex items-center justify-between bg-slate-950 p-3 rounded-lg border border-slate-850 text-xs">
                <div>
                  <span className="font-semibold text-slate-200 capitalize">{c.company}</span>
                  <span className="ml-2 px-2 py-0.5 rounded-full text-[10px] uppercase font-bold bg-indigo-950 text-indigo-300 border border-indigo-800">
                    {c.source}
                  </span>
                </div>
                <span className="text-slate-400 font-mono text-[11px]">
                  {c.config?.slug || c.config?.boardId || c.config?.host || c.config?.careersUrl || "configured"}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
