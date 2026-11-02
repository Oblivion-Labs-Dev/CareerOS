import styles from "./workspace-scene.module.css";

export type SceneKind = "discover" | "profile" | "settings" | "autopilot";

/** Decorative, code-native illustrations: no remote assets or fabricated metrics. */
export function WorkspaceScene({ kind = "discover", compact = false }: { kind?: SceneKind; compact?: boolean }) {
  return (
    <div className={`${styles.scene} ${compact ? styles.compact : ""}`} data-kind={kind} aria-hidden="true">
      <svg viewBox="0 0 360 220" fill="none">
        <ellipse cx="182" cy="191" rx="118" ry="12" className={styles.shadow} />
        <circle cx="185" cy="107" r="89" className={styles.halo} />
        <path d="M24 153C72 187 95 29 168 40s89 171 164 90" className={styles.path} />
        <g className={styles.spark}><path d="m305 45 3 10 10 3-10 3-3 10-3-10-10-3 10-3Z" fill="currentColor" /></g>
        <circle cx="51" cy="65" r="5" className={styles.dot} />
        {kind === "discover" && <>
          <g className={styles.back}><rect x="72" y="58" width="150" height="100" rx="14" transform="rotate(-12 72 58)" className={styles.sheetTint} /></g>
          <g className={styles.float}>
            <rect x="107" y="47" width="162" height="116" rx="14" className={styles.sheet} />
            <rect x="122" y="64" width="28" height="28" rx="8" className={styles.block} />
            <path d="m130 78 6-6 6 6-6 6Z" fill="white" />
            <path d="M163 71h76M163 84h44M123 110h111M123 122h83" className={styles.ink} />
            <rect x="122" y="139" width="42" height="8" rx="4" className={styles.halo} />
            <rect x="174" y="139" width="29" height="8" rx="4" className={styles.halo} />
          </g>
          <g className={styles.lens}><circle cx="244" cy="145" r="30" className={styles.glass} /><circle cx="244" cy="145" r="21" stroke="currentColor" strokeWidth="2" /><path d="m266 167 20 20" stroke="currentColor" strokeWidth="10" strokeLinecap="round" /></g>
        </>}
        {kind === "profile" && <>
          <g className={styles.back}><rect x="91" y="39" width="145" height="154" rx="12" transform="rotate(-10 91 39)" className={styles.sheetTint} /></g>
          <g className={styles.float}>
            <rect x="116" y="24" width="142" height="172" rx="12" className={styles.sheet} />
            <circle cx="149" cy="59" r="17" className={styles.halo} /><circle cx="149" cy="54" r="5" fill="currentColor" /><path d="M139 67c1-10 19-10 20 0" fill="currentColor" />
            <path d="M179 52h52M179 65h33M135 95h103M135 107h81M135 130h103M135 142h93M135 165h103M135 177h61" className={styles.ink} />
          </g>
          <g className={styles.lens}><circle cx="259" cy="153" r="27" className={styles.block} /><path d="m247 153 8 8 16-17" stroke="white" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" /></g>
        </>}
        {kind === "settings" && <>
          <g className={styles.back}><rect x="72" y="52" width="177" height="131" rx="19" transform="rotate(-9 72 52)" className={styles.sheetTint} /></g>
          <g className={styles.float}>
            <rect x="104" y="39" width="172" height="140" rx="18" className={styles.sheet} />
            <path d="M126 75h128M126 109h128M126 143h128" className={styles.track} />
            <g className={styles.slider}><circle cx="154" cy="75" r="11" className={styles.block} /><circle cx="222" cy="143" r="11" className={styles.block} /></g>
            <g className={styles.sliderReverse}><circle cx="217" cy="109" r="11" className={styles.block} /></g>
          </g>
          <g className={styles.lens}><rect x="57" y="138" width="63" height="32" rx="16" className={styles.block} /><circle cx="104" cy="154" r="11" fill="white" /></g>
        </>}
        {kind === "autopilot" && <>
          <circle cx="183" cy="111" r="68" className={styles.orbit} /><circle cx="183" cy="111" r="44" className={styles.orbit} />
          <g className={styles.plane}><path d="m106 104 150-51-51 130-30-55Z" className={styles.sheet} strokeWidth="3" /><path d="m175 128 81-75-65 91" stroke="currentColor" strokeWidth="2" /><path d="m175 128 5 37 11-21" className={styles.sheetTint} /></g>
          <g className={styles.lens}><circle cx="283" cy="153" r="21" className={styles.block} /><path d="m274 153 6 6 12-13" stroke="white" strokeWidth="3" strokeLinecap="round" /></g>
        </>}
      </svg>
    </div>
  );
}
