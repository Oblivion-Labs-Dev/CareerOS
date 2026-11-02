"use client";
import {useState} from "react";
import {useCareerProgress} from "./progress-provider";
import styles from "./progress.module.css";

export function ProgressHeader() {
  const {data,error,busy,refresh,mutate,celebration,dismiss} = useCareerProgress();
  const [editing,setEditing] = useState(false);
  const [goal,setGoal] = useState(3);
  const [timezone,setTimezone] = useState("UTC");
  const count = data?.completedCount ?? 0;
  const target = data?.preferences.weeklyGoal ?? 3;
  return <>
    <header className={styles.header}><div><h1>Dashboard</h1></div>
      <button className={styles.goalButton} disabled={!data} onClick={() => {setGoal(target);setTimezone(data?.preferences.timezone || "UTC");setEditing(value => !value);}} aria-expanded={editing} aria-label="Edit weekly goal" aria-describedby="weekly-goal-description">
        <span className={styles.ring} data-complete={data?.goalReached}><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="27"/><circle cx="32" cy="32" r="27" pathLength="100" strokeDasharray={`${Math.min(100,count/target*100)} 100`}/></svg><strong>{data ? `${count}/${target}` : "—"}</strong></span>
        <span><strong>{data?.goalReached ? "Weekly goal reached" : "Your weekly rhythm"}</strong><small id="weekly-goal-description">{data ? `${count} meaningful ${count === 1 ? "action" : "actions"} · edit goal ↗` : "Loading your progress…"}</small></span>
      </button>
    </header>
    {error && <p className={styles.error} role="alert">{error} <button onClick={refresh} disabled={busy}>Retry</button></p>}
    {editing && <form className={styles.preferences} onSubmit={async event => {event.preventDefault();if(await mutate("/preferences",{weeklyGoal:goal,timezone},"PUT")) setEditing(false);}}>
      <label>Weekly actions<select value={goal} onChange={event => setGoal(Number(event.target.value))}>{[1,2,3].map(n => <option key={n} value={n}>{n} meaningful {n === 1 ? "action" : "actions"}</option>)}</select></label>
      <label>Week timezone<input value={timezone} onChange={event => setTimezone(event.target.value)} required placeholder="America/Los_Angeles" /></label><button type="button" onClick={() => setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone)}>Use my timezone</button><button disabled={busy}>{busy ? "Saving…" : "Save goal"}</button>
      <p>Weeks begin on Monday. Choose your pace; taking time off never removes an achievement.</p>
    </form>}
    {celebration && <div className={styles.celebration} role="status"><span aria-hidden="true">✦</span><p>{celebration}</p><button aria-label="Dismiss celebration" onClick={dismiss}>×</button></div>}
  </>;
}
