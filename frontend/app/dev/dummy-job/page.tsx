import { DummyJobTestingApp } from "@/components/benchmark/dummy-job-testing-app";

export const metadata = {
  title: "Dummy Job Test Bed | CareerOS QA Sandbox",
  description: "Live autofill testing page with 40+ question variations, failure cases, and real-time LLM resolution inspector.",
};

export default function DummyJobPage() {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 py-6">
      <DummyJobTestingApp />
    </main>
  );
}
