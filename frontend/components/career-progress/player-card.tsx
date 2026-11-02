"use client";
import {useState} from "react";
import {useCareerProgress} from "./progress-provider";
import styles from "./progress.module.css";

export function PlayerCard() {
  const {data} = useCareerProgress();
  const [flipped,setFlipped] = useState(false);
  if (!data) return null;
  const initials = data.player.name.split(/\s+/).slice(0,2).map(word=>word[0]).join("");
  return <button className={styles.player} data-flipped={flipped} onClick={() => setFlipped(value=>!value)} aria-label={flipped ? "Show career card front" : "Turn career card to see personal records"} aria-pressed={flipped}>
    <span className={styles.playerInner}>
      <span className={styles.playerFace} aria-hidden={flipped}><span className={styles.cardTop}><span>CAREEROS / MEMBER</span><span>✧</span></span><span className={styles.playerInitials}>{initials}</span><strong className={styles.playerName}>{data.player.name}</strong><span className={styles.specialty}>{data.player.specialty}</span><span className={styles.cardBottom}><span>YOUR CAREER. YOUR PACE.</span><span>Personal records ↻</span></span></span>
      <span className={`${styles.playerFace} ${styles.playerBack}`} aria-hidden={!flipped}><span className={styles.cardTop}>YOUR PERSONAL RECORDS <span>✦</span></span><strong className={styles.recordNumber}>{data.records.bestWeekCount || "—"}</strong><span className={styles.specialty}>Most confirmed submissions in a week</span><span className={styles.badgeMini}>{data.milestones.filter(m=>m.earnedAt).map(m=><span key={m.id} title={m.title}>{m.symbol}</span>)}{!data.milestones.some(m=>m.earnedAt) && <small>Your first milestone belongs here.</small>}</span><span className={styles.cardBottom}><span>{data.records.confirmedTotal} ATS confirmations recorded</span><span>↻</span></span></span>
    </span>
  </button>;
}
