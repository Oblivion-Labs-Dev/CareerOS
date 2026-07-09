"use client";

import { useEffect, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

const POLL_MS = 5000;

export function useBackendStatus() {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/health`, { cache: "no-store" });
        if (!res.ok) {
          if (!cancelled) setOnline(false);
          return;
        }
        const data = (await res.json()) as { status?: string };
        if (!cancelled) setOnline(data.status === "ok");
      } catch {
        if (!cancelled) setOnline(false);
      }
    };

    void check();
    const id = window.setInterval(() => void check(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return online;
}
