"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./resume-studio/studio.module.css";

export default function ProfileLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return <>
    <nav className={styles.tabs} aria-label="Profile and resume">
      <Link href="/profile" aria-current={pathname === "/profile" ? "page" : undefined}>Profile & documents</Link>
      <Link href="/profile/resume-studio" aria-current={pathname.startsWith("/profile/resume-studio") ? "page" : undefined}>Resume Studio <span>NEW</span></Link>
    </nav>
    {children}
  </>;
}
