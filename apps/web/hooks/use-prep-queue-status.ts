"use client";

import { useCallback, useEffect, useState } from "react";
import { getPrepQueueStatus, type PrepQueueStatus } from "@/lib/application-assistant-api";

export function usePrepQueueStatus(pollMs = 2000) {
  const [status, setStatus] = useState<PrepQueueStatus | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await getPrepQueueStatus();
      setStatus(res);
    } catch {
      /* queue status optional */
    }
  }, []);

  useEffect(() => {
    const poll = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    poll();
    const id = setInterval(poll, pollMs);
    document.addEventListener("visibilitychange", poll);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", poll);
    };
  }, [refresh, pollMs]);

  return { status, refresh };
}
