import { redirect } from "next/navigation";

/** The compiler now lives inside Resume Studio. Old links (and ?job=) keep working. */
export default async function ResumeCompilerRedirect({ searchParams }: { searchParams: Promise<{ job?: string }> }) {
  const { job } = await searchParams;
  redirect(job ? `/profile/resume-studio?job=${encodeURIComponent(job)}` : "/profile/resume-studio");
}
