"use client";

import { useEffect, useState } from "react";
import styles from "./motion-control.module.css";

export function MotionControl() {
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    try {
      const saved = localStorage.getItem("careeros-motion") === "paused";
      setPaused(saved);
      document.documentElement.dataset.motion = saved ? "paused" : "on";
    } catch { /* Browser storage is optional. */ }
  }, []);

  const toggle = () => {
    const next = !paused;
    setPaused(next);
    document.documentElement.dataset.motion = next ? "paused" : "on";
    try { localStorage.setItem("careeros-motion", next ? "paused" : "on"); } catch { /* Keep the session preference. */ }
  };

  return <button className={styles.button} type="button" onClick={toggle} aria-pressed={paused} aria-label={paused ? "Resume page animations" : "Pause page animations"} title={paused ? "Resume page animations" : "Pause page animations"}>
    <svg width="17" height="17" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      {paused ? <path d="m7 4 9 6-9 6Z" fill="currentColor" /> : <><path d="M7 5v10M13 5v10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /><circle cx="10" cy="10" r="9" stroke="currentColor" opacity=".3" /></>}
    </svg>
  </button>;
}
