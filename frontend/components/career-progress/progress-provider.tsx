"use client";
import {createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode} from "react";

export type Quest = {id: string; title: string; detail: string; href: string; action: string; symbol: string; completedAt: string | null};
export type Milestone = {id: string; title: string; description: string; symbol: string; earnedAt: string | null; seen: boolean};
export type Progress = {
  week: string; preferences: {weeklyGoal: number; timezone: string}; completedCount: number; goalReached: boolean;
  player: {name: string; specialty: string}; quests: Quest[]; milestones: Milestone[];
  records: {confirmedTotal: number; datedConfirmed: number; bestWeekCount: number; bestWeek: string | null; thisWeekCount: number; bestDayCount: number; bestDays: string[]};
  history: {id: string; questId: string; week: string; at: string; source: string}[];
};
type Context = {data: Progress | null; error: string; busy: boolean; refresh: () => void; mutate: (path: string, body?: unknown, method?: string) => Promise<boolean>; celebration: string | null; dismiss: () => void};
const ProgressContext = createContext<Context | null>(null);
const BASE = "/api/backend/application-assistant/progress";

async function request(path = "", body?: unknown, method = "GET") {
  const response = await fetch(BASE+path, {method, headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store", signal: AbortSignal.timeout(20000)});
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : "Progress could not be saved. Please try again.");
  }
  return response.json() as Promise<Progress>;
}

export function ProgressProvider({children}: {children: ReactNode}) {
  const [data,setData] = useState<Progress | null>(null);
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  const [celebration,setCelebration] = useState<string | null>(null);
  const version = useRef(0);
  const writing = useRef(false);
  const current = useRef<Progress | null>(null);
  const accept = useCallback((next: Progress) => {
    const previous = current.current;
    if (previous) {
      const earned = next.milestones.find(m => m.earnedAt && !previous.milestones.find(old => old.id === m.id)?.earnedAt);
      if (earned) setCelebration(`Milestone unlocked: ${earned.title}`);
      else if (next.goalReached && !previous.goalReached) setCelebration("Your weekly goal is complete. Make room to enjoy the progress.");
      else if (next.completedCount > previous.completedCount) setCelebration("A meaningful step, recorded.");
    }
    current.current=next; setData(next);
  }, []);
  const refresh = useCallback(() => {
    if (writing.current) return;
    const generation = ++version.current;
    void request().then(next => {if (version.current === generation) {accept(next);setError("");}}).catch(() => {if (version.current === generation) setError("Career progress is unavailable. Your saved progress has not been changed.");});
  }, [accept]);
  const invalidate = useCallback(() => {version.current++;}, []);
  useEffect(() => {
    refresh();
    const timer = setInterval(() => {if (!document.hidden) refresh();},60000);
    return () => {clearInterval(timer);invalidate();};
  }, [refresh,invalidate]);
  const mutate = async (path: string, body?: unknown, method = "POST") => {
    if (writing.current) return false;
    writing.current=true; ++version.current; setBusy(true);setError("");
    try {accept(await request(path,body,method)); return true;}
    catch (failure) {setError(failure instanceof Error ? failure.message : "Unable to save progress");return false;}
    finally {writing.current=false;setBusy(false);}
  };
  return <ProgressContext.Provider value={{data,error,busy,refresh,mutate,celebration,dismiss:()=>setCelebration(null)}}>{children}</ProgressContext.Provider>;
}

export function useCareerProgress() {
  const context = useContext(ProgressContext);
  if (!context) throw new Error("Career progress requires its provider");
  return context;
}
