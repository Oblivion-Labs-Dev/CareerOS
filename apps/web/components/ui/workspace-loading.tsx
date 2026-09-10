import styles from "./workspace-loading.module.css";

export function WorkspaceLoading({ label }: { label: string }) {
  return <div className={styles.loading} role="status" aria-label={label}><span>{label}</span><div aria-hidden="true"><i /><i /><i /></div></div>;
}
