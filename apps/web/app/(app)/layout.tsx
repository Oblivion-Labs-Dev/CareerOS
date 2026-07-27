import { AppSidebar } from "@/components/app-sidebar";
import { AppTopbar } from "@/components/app-topbar";
import { BackendOfflineAlert } from "@/components/backend-offline-alert";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <AppSidebar />
      <div className="app-stage">
        <AppTopbar />
        <BackendOfflineAlert />
        <main id="main-content" className="main" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
