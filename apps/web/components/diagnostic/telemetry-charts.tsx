"use client";
import {useState} from "react";
import type {DiagnosticSeries,MetricBucket} from "@/lib/diagnostic-api";
import styles from "./telemetry-charts.module.css";
const series = [{key:"submitted",label:"Submitted",color:"var(--success)"},{key:"failed",label:"Failed",color:"var(--danger)"},{key:"review",label:"Review",color:"var(--warning)"},{key:"skipped",label:"Skipped",color:"#638df5"},{key:"other",label:"Other",color:"var(--muted)"}] as const;
export function TelemetryCharts({data,loading}:{data:DiagnosticSeries|null;loading:boolean}) {
  const [active,setActive]=useState<number|null>(null);
  const [hidden,setHidden]=useState<string[]>([]);
  if(!data)return <section className={styles.panel} aria-label="Telemetry charts"><h2>Activity over time</h2><p>{loading?"Loading recorded telemetry…":"Telemetry unavailable. Refresh to try again."}</p></section>;
  const rows=data.buckets;
  const visible=series.filter(s=>!hidden.includes(s.key));
  const total=(r:MetricBucket)=>visible.reduce((sum,s)=>sum+r[s.key],0);
  const max=Math.max(1,...rows.map(total));
  const selected=active===null?null:rows[active];
  const time=(t:string)=>new Date(t).toLocaleString([], {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});
  const durations=rows.filter(r=>r.durationSec!==null);
  const durationMax=Math.max(1,...durations.map(r=>r.durationSec!));
  const outcomes=series.map(s=>({...s,count:rows.reduce((sum,r)=>sum+r[s.key],0)}));
  const overall=outcomes.reduce((sum,s)=>sum+s.count,0);
  const lineSegments: string[]=[];let segment="";
  rows.forEach((r,i)=>{if(r.durationSec===null){if(segment)lineSegments.push(segment);segment="";}else segment+=`${segment?" L":"M"}${35+i*630/Math.max(1,rows.length-1)},${160-r.durationSec/durationMax*130}`;});if(segment)lineSegments.push(segment);
  return <section className={styles.root} aria-label="Telemetry charts">
    <article className={`${styles.panel} ${styles.wide}`}><div className={styles.heading}><div><span className={styles.eyebrow}>WORKLOAD SIGNAL</span><h2>Activity over time</h2></div><span>{data.bucketSeconds/60}-minute buckets</span></div>
      <div className={styles.legend}>{series.map(s=><button key={s.key} aria-pressed={!hidden.includes(s.key)} onClick={()=>setHidden(v=>v.includes(s.key)?v.filter(k=>k!==s.key):[...v,s.key])}><i style={{background:s.color}}/>{s.label}</button>)}</div>
      <div className={styles.plot}><div className={styles.scale}><span>{max} jobs</span><span>{Math.round(max/2)}</span><span>0</span></div><div className={styles.bars}>{rows.map((r,i)=><button key={r.timestamp} onFocus={()=>setActive(i)} onMouseEnter={()=>setActive(i)} onClick={()=>setActive(i)} aria-label={`${time(r.timestamp)}: ${series.map(s=>`${r[s.key]} ${s.label}`).join(", ")}`} className={styles.bar}>{visible.map(s=><span key={s.key} style={{height:`${r[s.key]/max*100}%`,background:s.color}}/>)}</button>)}</div></div>
      <div className={styles.axis}><span>{rows[0]&&time(rows[0].timestamp)}</span><span>{time(data.updatedAt)}</span></div>
      <p className={styles.readout} aria-live="polite">{selected?`${time(selected.timestamp)} · ${series.map(s=>`${s.label} ${selected[s.key]}`).join(" · ")}`:overall?"Hover, focus, or tap a bucket to inspect its counts.":"No recorded job updates in this period."}</p>
    </article>
    <article className={styles.panel}><span className={styles.eyebrow}>RECORDED TIMING</span><h2>Checkpoint duration</h2><p>Mean span per bucket · seconds</p>
      {durations.length?<svg viewBox="0 0 700 195" role="img" aria-label="Average recorded checkpoint duration by time bucket"><text x="0" y="18" fill="currentColor" fontSize="16">{durationMax.toFixed(0)}s</text>{[30,95,160].map(y=><line key={y} x1="35" x2="665" y1={y} y2={y} stroke="currentColor" opacity=".12"/>)}{lineSegments.map((d,i)=><path key={i} d={d} fill="none" stroke="var(--accent)" strokeWidth="3"/>)}{rows.map((r,i)=>r.durationSec===null?null:<circle key={r.timestamp} cx={35+i*630/Math.max(1,rows.length-1)} cy={160-r.durationSec/durationMax*130} r="4" fill="var(--accent)"><title>{time(r.timestamp)}: {r.durationSec}s, {r.samples} samples</title></circle>)}<text x="0" y="165" fill="currentColor" fontSize="16">0s</text></svg>:<div className={styles.empty}>No checkpoint timing samples in this period.</div>}
      <p>{durations.reduce((sum,r)=>sum+r.samples,0)} samples · gaps mean no timing recorded</p></article>
    <article className={styles.panel}><span className={styles.eyebrow}>OUTCOME DISTRIBUTION</span><h2>{overall.toLocaleString()} jobs updated</h2><div className={styles.outcomes}>{outcomes.map(s=><div key={s.key}><span>{s.label}</span><div><i style={{width:`${overall?s.count/overall*100:0}%`,background:s.color}}/></div><strong>{s.count}</strong></div>)}</div><p>Current status of jobs updated in this period.</p></article>
    <details className={styles.table}><summary>Inspect chart data & definitions</summary><p>{data.basis}</p><div><table><caption>Recorded telemetry buckets</caption><thead><tr><th>Bucket start</th>{series.map(s=><th key={s.key}>{s.label}</th>)}<th>Mean duration</th><th>Samples</th></tr></thead><tbody>{rows.map(r=><tr key={r.timestamp}><th>{time(r.timestamp)}</th>{series.map(s=><td key={s.key}>{r[s.key]}</td>)}<td>{r.durationSec===null?"Not recorded":`${r.durationSec}s`}</td><td>{r.samples}</td></tr>)}</tbody></table></div></details>
  </section>;
}
