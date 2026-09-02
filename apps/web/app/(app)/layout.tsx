import { AppSidebar } from "@/components/app-sidebar";
import { AppTopbar } from "@/components/app-topbar";
import { BackendOfflineAlert } from "@/components/backend-offline-alert";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
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
import { Suspense } from "react";
