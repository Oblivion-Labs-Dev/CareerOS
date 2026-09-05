"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createResumeProfile,
  deleteResumeProfile,
  listResumeProfiles,
  patchResumeProfile,
  setDefaultResumeProfile,
  type ResumeProfile,
} from "@/lib/resume-profiles-api";

type Props = {
  activeProfileId: string | null;
  onSelect: (profile: ResumeProfile) => void;
  onChanged?: (profiles: ResumeProfile[]) => void;
};

const pillBase: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "0.4rem",
  padding: "0.4rem 0.75rem",
  borderRadius: "var(--radius-full)",
  border: "1px solid var(--border)",
  background: "var(--card)",
  color: "var(--text-secondary)",
  fontSize: "var(--cos-text-sm)",
  cursor: "pointer",
};

export function ResumeProfileSwitcher({ activeProfileId, onSelect, onChanged }: Props) {
  const [profiles, setProfiles] = useState<ResumeProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await listResumeProfiles();
      setProfiles(list);
      onChanged?.(list);
      if (!activeProfileId && list.length) {
        const preferred = list.find((p) => p.isDefault) ?? list[0];
        onSelect(preferred);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load resume profiles");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    setError("");
    try {
      const profile = await createResumeProfile(name);
      setNewName("");
      setCreating(false);
      const list = await listResumeProfiles();
      setProfiles(list);
      onChanged?.(list);
      onSelect(profile);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create profile");
    }
  };

  const handleRename = async (profile: ResumeProfile) => {
    const name = window.prompt("Rename profile", profile.name);
    if (!name || !name.trim() || name.trim() === profile.name) return;
    const updated = await patchResumeProfile(profile.id, { name: name.trim() });
    setProfiles((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    if (activeProfileId === updated.id) onSelect(updated);
  };

  const handleDelete = async (profile: ResumeProfile) => {
    if (profiles.length <= 1) return;
    if (!window.confirm(`Delete "${profile.name}"? This can't be undone.`)) return;
    await deleteResumeProfile(profile.id);
    await refresh();
  };

  const handleSetDefault = async (profile: ResumeProfile) => {
    const updated = await setDefaultResumeProfile(profile.id);
    setProfiles((prev) => prev.map((p) => ({ ...p, isDefault: p.id === updated.id })));
  };

  if (loading) {
    return <p className="muted dashboard-empty">Loading resume profiles…</p>;
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.5rem" }}>
      {profiles.map((profile) => {
        const active = profile.id === activeProfileId;
        return (
          <div key={profile.id} style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
            <button
              type="button"
              onClick={() => onSelect(profile)}
              style={{
                ...pillBase,
                borderColor: active ? "var(--accent)" : "var(--border)",
                background: active ? "var(--accent-soft, rgba(88, 222, 196, 0.12))" : "var(--card)",
                color: active ? "var(--accent)" : "var(--text-secondary)",
                fontWeight: active ? 650 : 500,
              }}
              title={profile.resume?.updatedAt ? `Updated ${new Date(profile.resume.updatedAt).toLocaleDateString()}` : undefined}
            >
              {profile.isDefault ? <span aria-hidden>★</span> : null}
              {profile.name}
            </button>
            <button
              type="button"
              onClick={() => void handleRename(profile)}
              aria-label={`Rename ${profile.name}`}
              style={{ ...pillBase, padding: "0.3rem 0.5rem", fontSize: "var(--cos-text-xs)" }}
            >
              ✎
            </button>
            {!profile.isDefault ? (
              <button
                type="button"
                onClick={() => void handleSetDefault(profile)}
                aria-label={`Set ${profile.name} as default`}
                style={{ ...pillBase, padding: "0.3rem 0.5rem", fontSize: "var(--cos-text-xs)" }}
              >
                Set default
              </button>
            ) : null}
            {profiles.length > 1 ? (
              <button
                type="button"
                onClick={() => void handleDelete(profile)}
                aria-label={`Delete ${profile.name}`}
                style={{ ...pillBase, padding: "0.3rem 0.5rem", fontSize: "var(--cos-text-xs)", color: "#f43f5e", borderColor: "rgba(244,63,94,0.35)" }}
              >
                Delete
              </button>
            ) : null}
          </div>
        );
      })}

      {creating ? (
        <div style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleCreate();
              if (e.key === "Escape") setCreating(false);
            }}
            placeholder="e.g. Fintech"
            style={{
              padding: "0.4rem 0.6rem",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              background: "var(--card)",
              color: "var(--text)",
              fontSize: "var(--cos-text-sm)",
              width: "9rem",
            }}
          />
          <button type="button" className="btn btn-sm btn-primary" onClick={() => void handleCreate()}>
            Add
          </button>
        </div>
      ) : (
        <button type="button" className="btn btn-sm" onClick={() => setCreating(true)}>
          + New profile
        </button>
      )}

      {error ? <span style={{ color: "#f43f5e", fontSize: "var(--cos-text-xs)" }}>{error}</span> : null}
    </div>
  );
}
