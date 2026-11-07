import { Suspense } from "react";
import { AppSidebar } from "@/components/app-sidebar";
import { AppTopbar } from "@/components/app-topbar";
import { BackendOfflineAlert } from "@/components/backend-offline-alert";
import { CinematicBackdrop } from "@/components/cinematic/cinematic-backdrop";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
      <CinematicBackdrop />
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <Suspense fallback={<aside className="sidebar" aria-hidden="true" />}>
        <AppSidebar />
      </Suspense>
      <div className="app-stage">
        <Suspense fallback={<header className="app-topbar" aria-hidden="true" />}>
          <AppTopbar />
        </Suspense>
        <BackendOfflineAlert />
        <main id="main-content" className="main" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
