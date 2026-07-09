import { BackendIcon } from "@/components/backend-icon";
import { BACKEND_BANNER_OFFLINE, BACKEND_BANNER_ONLINE, BACKEND_START_COMMAND } from "@/lib/nav-config";
import { fetchHealth, getApiBaseUrl } from "@/lib/api";

export async function BackendRequiredBanner() {
  const health = await fetchHealth().catch(() => ({ status: "offline" }));
  const online = health.status === "ok";
  const apiUrl = getApiBaseUrl();

  return (
    <section
      className={`backend-required-banner${online ? " backend-required-banner--online" : " backend-required-banner--offline"}`}
      aria-label="Backend server status"
    >
      <div className="backend-required-banner-icon" aria-hidden>
        <BackendIcon className="backend-required-banner-svg" />
      </div>
      <div className="backend-required-banner-body">
        <div className="backend-required-banner-heading">
          <strong>{online ? "Backend connected" : "Backend server required"}</strong>
          <span className="backend-required-banner-url">{apiUrl}</span>
        </div>
        {online ? <p>{BACKEND_BANNER_ONLINE}</p> : (
          <>
            <p>{BACKEND_BANNER_OFFLINE}</p>
            <pre className="backend-required-banner-command">
              <code>{BACKEND_START_COMMAND}</code>
            </pre>
          </>
        )}
      </div>
      <span className={`backend-required-banner-pill${online ? " backend-required-banner-pill--online" : ""}`}>
        {online ? "Online" : "Offline"}
      </span>
    </section>
  );
}
