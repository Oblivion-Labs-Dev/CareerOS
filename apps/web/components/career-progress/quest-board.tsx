"use client";
import {useState} from "react";
import {SidePanelPortal} from "@/components/side-panel-portal";
import {WorkspaceLoading} from "@/components/ui/workspace-loading";
import {useCareerProgress} from "./progress-provider";
import {PlayerCard} from "./player-card";
import {MilestoneCollection} from "./milestone-collection";
import styles from "./progress.module.css";

export function QuestBoard() {
  const {data,busy,mutate,error} = useCareerProgress();
  const [focus,setFocus] = useState<string | null>(null);
  const quest = data?.quests.find(item=>item.id===focus);
  if (!data) return error ? null : <WorkspaceLoading label="Loading your weekly quests…" />;
  const complete = (id: string) => mutate(`/quests/${id}/complete`,{week:data.week});
  return <section className={styles.progressBoard} aria-label="Career progress">
    <div className={styles.boardHeading}><div><span className={styles.eyebrow}>PROGRESS WITH PURPOSE</span><h2>A little momentum, every week.</h2></div><span className={styles.week}>Week of {data.week} · {data.preferences.timezone}</span></div>
    <div className={styles.boardGrid}><PlayerCard/><div className={styles.quests}>{data.quests.map((item,index)=><button key={item.id} className={styles.quest} data-complete={Boolean(item.completedAt)} onClick={()=>setFocus(item.id)}><span className={styles.questSymbol}>{item.completedAt ? "✓" : item.symbol}</span><span><small>QUEST 0{index+1} · {item.completedAt ? "COMPLETE" : "YOUR PACE"}</small><strong>{item.title}</strong></span><span aria-hidden="true">{item.completedAt ? "✓" : "↗"}</span></button>)}</div></div>
    <MilestoneCollection/>
    <details className={styles.history}><summary>Your recent check-ins <span>{data.history.length}</span></summary>{data.history.length ? <ol>{data.history.map(event=><li key={event.id}><span>{data.quests.find(item=>item.id===event.questId)?.title || event.questId}</span><time dateTime={event.at}>{new Date(event.at).toLocaleDateString()}</time><small>Confirmed by you</small></li>)}</ol> : <p>Your completed quests will be saved here.</p>}</details>
    <SidePanelPortal open={Boolean(quest)} onClose={()=>setFocus(null)} panelClassName={styles.focusPanel} ariaLabelledBy="quest-title">
      {quest && <div className={styles.focusContent}><div className={styles.focusTop}><span>FOCUS MODE</span><button onClick={()=>setFocus(null)} aria-label="Close focus mode">×</button></div><div className={styles.focusSteps} aria-label={`Quest ${data.quests.findIndex(item=>item.id===quest.id)+1} of 3`}>{data.quests.map(item=><span key={item.id} data-active={item.id===quest.id} data-complete={Boolean(item.completedAt)}/>)}</div><span className={styles.focusSymbol} data-complete={Boolean(quest.completedAt)}>{quest.completedAt ? "✓" : quest.symbol}</span><span className={styles.eyebrow}>{quest.completedAt ? "A STEP FORWARD" : "ONE THING AT A TIME"}</span><h2 id="quest-title">{quest.title}</h2><p>{quest.detail}</p>
        {quest.completedAt ? <><p className={styles.completedNote}>Completed {new Date(quest.completedAt).toLocaleString()}. Your check-in is saved.</p><button className={styles.primary} onClick={()=>setFocus(data.quests.find(item=>!item.completedAt)?.id || null)}>{data.quests.some(item=>!item.completedAt) ? "Next quest →" : "Back to your dashboard"}</button></> : <><a className={styles.openTask} href={quest.href} target="_blank" rel="noopener noreferrer">{quest.action} ↗</a><button className={styles.primary} disabled={busy} onClick={()=>void complete(quest.id)}>{busy ? "Saving your progress…" : "I completed this action ✓"}</button><small className={styles.disclosure}>This is your check-in, not an automated verification. Only mark it complete after doing the action.</small></>}
        {error && <p role="alert" className={styles.error}>{error}</p>}
      </div>}
    </SidePanelPortal>
  </section>;
}
