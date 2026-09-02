"use client";

import { useSyncExternalStore } from "react";

const POLL_MS = 15_000;
const HEALTH_TIMEOUT_MS = 5_000;

type Listener = () => void;

let online: boolean | null = null;
let pollId: number | null = null;
let subscriberCount = 0;
const listeners = new Set<Listener>();

function emit() {
  for (const listener of listeners) {
    listener();
  }
}

async function checkHealth(): Promise<boolean> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
  try {
    // Health follows the same-origin proxy so a dashboard opened from another
    // device (or a browser that resolves "localhost" to ::1) never fails to
    // reach a backend that's actually up.
    const res = await fetch("/api/backend/health", {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { status?: string };
    return data.status === "ok" || res.status === 200;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}

async function runHealthCheck() {
  const next = await checkHealth();
  if (next !== online) {
    online = next;
    emit();
    resetPollInterval();
  } else if (online === null) {
    online = next;
    emit();
    resetPollInterval();
  }
}

function resetPollInterval() {
  if (pollId !== null) {
    window.clearInterval(pollId);
    pollId = null;
  }
  if (subscriberCount > 0) {
    const interval = online === false ? 3_000 : POLL_MS;
    pollId = window.setInterval(pollHealth, interval);
  }
}

function pollHealth() {
  if (document.visibilityState === "visible") void runHealthCheck();
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  subscriberCount += 1;
  if (subscriberCount === 1) {
    pollHealth();
    resetPollInterval();
    document.addEventListener("visibilitychange", pollHealth);
  }
  return () => {
    listeners.delete(listener);
    subscriberCount -= 1;
    if (subscriberCount === 0) {
      document.removeEventListener("visibilitychange", pollHealth);
      if (pollId !== null) {
        window.clearInterval(pollId);
        pollId = null;
      }
    }
  };
}

function getSnapshot() {
  return online;
}

function getServerSnapshot() {
  return null;
}

export function refreshBackendStatus() {
  void runHealthCheck();
}

export function useBackendStatus() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export function BackendStatusInit() {
  useBackendStatus();
  return null;
}
