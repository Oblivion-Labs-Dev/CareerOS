import { Suspense } from "react";

import nextDynamic from "next/dynamic";

import { PageTitleWithStatus } from "@/components/page-title-with-status";

import { ApplicationAssistantDashboard } from "@/components/application-assistant/application-assistant-dashboard";



const QwenAgentPanel = nextDynamic(

  () => import("@/components/qwen/qwen-agent-panel").then((mod) => mod.QwenAgentPanel),

  { loading: () => <p className="muted">Loading Qwen agent…</p> },

);



function ApplicationQueueLoading() {

  return (

    <div className="aa-bootstrapping" role="status" aria-label="Loading applications">

      <span className="page-loading-bar" />

      <p className="muted">Loading applications…</p>

    </div>

  );

}



export default function ApplicationAssistantPage() {

  return (

    <div className="page-content aa-page">

      <header className="cos-page-header aa-page-header">

        <div className="stack gap-xs">
          <span className="toc-eyebrow">Intelligence Layer</span>

          <PageTitleWithStatus>AI Assistant</PageTitleWithStatus>

          <p className="muted">

            Prep applications in a visible browser and track what still needs your input.

          </p>

        </div>
      </header>

      <Suspense fallback={<ApplicationQueueLoading />}>

        <ApplicationAssistantDashboard />

      </Suspense>

      <QwenAgentPanel />

    </div>

  );

}


