import { readFileSync } from "node:fs";
import path from "node:path";
import { InterviewChecklistView, type InterviewChecklist } from "./checklist-view";

function loadChecklist(): InterviewChecklist {
  const candidates = [
    path.resolve(process.cwd(), "../../data/profile/interview-prep-checklist.json"),
    path.resolve(process.cwd(), "data/profile/interview-prep-checklist.json"),
  ];
  for (const candidate of candidates) {
    try {
      return JSON.parse(readFileSync(candidate, "utf8")) as InterviewChecklist;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
  throw new Error("Interview checklist is missing from data/profile/interview-prep-checklist.json");
}

export default function InterviewPrepPage() {
  return <InterviewChecklistView checklist={loadChecklist()} />;
}
