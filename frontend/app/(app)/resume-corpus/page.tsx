import { ResumeCorpusClient } from "./resume-corpus-client";
import { isCorpusView } from "./corpus-navigation";

interface ResumeCorpusPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ResumeCorpusPage({ searchParams }: ResumeCorpusPageProps) {
  const params = await searchParams;
  const requestedView = first(params.view) ?? null;
  return (
    <ResumeCorpusClient
      previewMode={first(params.preview) === "1"}
      initialView={isCorpusView(requestedView) ? requestedView : "overview"}
      initialRecordId={first(params.record)}
    />
  );
}
