"use client";
import { useEffect, useState, type Dispatch, type SetStateAction } from "react";

export function useSessionState<T>(key: string, fallback: T): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState(fallback);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    try { const saved = sessionStorage.getItem(key); if (saved !== null) setValue(JSON.parse(saved)); } catch { /* Storage may be disabled. */ }
    setReady(true);
  }, [key]);
  useEffect(() => {if (ready) {try {sessionStorage.setItem(key,JSON.stringify(value));} catch { /* Keep controls usable. */ }}}, [key,ready,value]);
  return [value,setValue];
}
