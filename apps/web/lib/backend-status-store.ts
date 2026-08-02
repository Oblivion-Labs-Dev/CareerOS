"use client";

import { useSyncExternalStore } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

const POLL_MS = 15_000;
const HEALTH_TIMEOUT_MS = 2_000;

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
    const res = await fetch(`${getClientApiBaseUrl()}/health`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { status?: string };
    return data.status === "ok";
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
  } else if (online === null) {
    online = next;
    emit();
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
    pollId = window.setInterval(pollHealth, POLL_MS);
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
