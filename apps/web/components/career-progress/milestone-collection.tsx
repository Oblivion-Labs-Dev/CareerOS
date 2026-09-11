"use client";
import {useState} from "react";
import {useCareerProgress} from "./progress-provider";
import styles from "./progress.module.css";

export function MilestoneCollection() {
  const {data,busy,mutate} = useCareerProgress();
  const [selected,setSelected] = useState<string | null>(null);
  if (!data) return null;
  const milestone = data.milestones.find(item=>item.id===selected);
  return <details className={styles.collection}><summary><span>✧ <strong>Your milestone collection</strong></span><span>{data.milestones.filter(item=>item.earnedAt).length} / {data.milestones.length} earned · Explore</span></summary><div className={styles.tokens}>{data.milestones.map(item=><button key={item.id} disabled={!item.earnedAt || busy} className={styles.token} data-earned={Boolean(item.earnedAt)} aria-label={`${item.title}${item.earnedAt ? ", earned" : ", not yet earned"}`} onClick={()=>{setSelected(item.id);if(!item.seen) void mutate(`/milestones/${item.id}/seen`);}}><span className={styles.coin}>{item.symbol}</span><strong>{item.title}</strong><small>{item.earnedAt ? new Date(item.earnedAt).toLocaleDateString() : "Still ahead"}</small></button>)}</div>
    {milestone && <div className={styles.badgeReveal} key={milestone.id} data-offer={milestone.id === "first_offer"}><span className={styles.coin}>{milestone.symbol}</span><div><span className={styles.eyebrow}>EARNED, NOT GIVEN</span><h3>{milestone.title}</h3><p>{milestone.description}</p><small>{milestone.earnedAt && new Date(milestone.earnedAt).toLocaleString()}</small></div><button aria-label="Close milestone detail" onClick={()=>setSelected(null)}>×</button>{milestone.id === "first_offer" && <div className={styles.confetti} aria-hidden="true">{Array.from({length:12},(_,i)=><i key={i} style={{left:`${i*8}%`,animationDelay:`${i*35}ms`}}/>)}</div>}</div>}
  </details>;
}
