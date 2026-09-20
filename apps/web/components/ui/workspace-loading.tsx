import styles from "./workspace-loading.module.css";

/**
 * The loading placeholder every workspace uses.
 *
 * Already the app's one loading primitive, with call sites across the
 * applications view, job discovery, the trackers, analytics and the quest
 * board. `shape` was added rather than a second component being introduced
 * beside it: two placeholder systems would drift apart, and the rule here is
 * one implementation per capability.
 *
 * The default shape is the original three-bar card, so every existing call site
 * renders exactly as before. The other shapes exist because a placeholder is
 * most useful when it is the size and arrangement of the content that is
 * coming — the layout then holds still when the data lands instead of jumping.
 *
 * Bars carry the global `.skeleton` class from design-language.css, which is
 * where the sheen and its `prefers-reduced-motion` opt-in live. With motion
 * reduced the bars still render, just still: the information is in the shape.
 */
export function WorkspaceLoading({
  label,
  shape = "panel",
  rows = 3,
}: {
  label: string;
  /** panel: a card of lines. list: repeated rows. grid: tiles. */
  shape?: "panel" | "list" | "grid";
  /** How many rows or tiles to stand in for. Ignored by `panel`. */
  rows?: number;
}) {
  if (shape === "panel") {
    return (
      <div className={styles.loading} role="status" aria-busy="true" aria-label={label}>
        <span>{label}</span>
        <div aria-hidden="true">
          <i className="skeleton" />
          <i className="skeleton" />
          <i className="skeleton" />
        </div>
      </div>
    );
  }

  return (
    <div
      className={shape === "grid" ? styles.grid : styles.list}
      role="status"
      aria-busy="true"
      aria-label={label}
    >
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className={styles.cell} aria-hidden="true">
          <i className="skeleton" style={{ width: "45%" }} />
          <i className="skeleton" style={{ width: "85%", height: "1.1rem" }} />
          <i className="skeleton" style={{ width: "60%" }} />
        </div>
      ))}
      <span className={styles.srOnly}>{label}</span>
    </div>
  );
}
