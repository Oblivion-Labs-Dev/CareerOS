"use client";
import {useEffect,useRef} from "react";

export function useApplicationScroll(key: string, loading: boolean, hasMore: boolean, count: number, loadMore: () => void) {
  const target = useRef<number | null>(null);
  useEffect(() => {
    try {target.current = Number(sessionStorage.getItem(`scroll:${key}`)) || null;} catch {target.current=null;}
    const save = () => {if (target.current === null) {try {sessionStorage.setItem(`scroll:${key}`,String(window.scrollY));} catch { /* Optional storage. */ }}};
    const cancel = () => {target.current=null;};
    window.addEventListener("scroll",save,{passive:true});
    window.addEventListener("wheel",cancel,{passive:true}); window.addEventListener("touchstart",cancel,{passive:true});
    return () => {window.removeEventListener("scroll",save);window.removeEventListener("wheel",cancel);window.removeEventListener("touchstart",cancel);};
  }, [key]);
  useEffect(() => {
    if (target.current === null || loading) return;
    const y = target.current;
    if (document.documentElement.scrollHeight-innerHeight < y && hasMore) {loadMore(); return;}
    window.scrollTo({top:y,behavior:"instant"}); target.current=null;
  }, [loading,hasMore,count,loadMore]);
}
