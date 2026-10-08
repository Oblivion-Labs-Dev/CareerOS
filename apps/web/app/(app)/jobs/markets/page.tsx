import { Suspense } from "react";
import { MarketsDashboard } from "@/components/markets/markets-dashboard";
import { WorkspaceLoading } from "@/components/ui/workspace-loading";

export const metadata = { title: "Markets · CareerOS" };

export default function MarketsPage() {
  return (
    <Suspense fallback={<WorkspaceLoading label="Loading markets…" shape="grid" rows={8} />}>
      <MarketsDashboard marketId="seattle" />
    </Suspense>
  );
}
