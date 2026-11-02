import { saveApplication } from './repositories/applicationRepository';
import { saveJob } from './repositories/jobRepository';
import { saveLearnedAnswer } from './repositories/learnedAnswerRepository';
import { saveDocument } from './repositories/documentRepository';
import { logChronicle as logActivityEvent } from './repositories/chronicleRepository';
import { generateId } from '../shared/id';

export async function seedDummyData() {
  // 1. Seed Documents
  const resume = await saveDocument({
    type: "resume",
    label: "Main Software Engineer Variant",
    fileName: "Jane_Doe_Resume_2026.pdf",
    active: true
  });

  const coverLetter = await saveDocument({
    type: "cover_letter",
    label: "Default Tech Startup Template",
    fileName: "Startup_Cover_Letter.pdf",
    active: true
  });

  // 2. Seed Jobs & Applications
  const jobsData = [
    {
      companyName: "Google",
      title: "Senior Software Engineer (L5) - Cloud",
      location: "Sunnyvale, CA (Hybrid)",
      url: "https://www.google.com/about/careers",
      status: "interviewing" as const,
      priority: "high" as const,
      fitScore: 94,
      notes: "First technical round completed on Monday. Recruiter says team match is with GCP databases team.",
      dateOffset: -12
    },
    {
      companyName: "Stripe",
      title: "Frontend Architect - Billing Platform",
      location: "San Francisco, CA (Hybrid)",
      url: "https://stripe.com/jobs",
      status: "submitted" as const,
      priority: "high" as const,
      fitScore: 89,
      notes: "Applied using custom Frontend Variant. Reached out to engineering manager via LinkedIn.",
      dateOffset: -7
    },
    {
      companyName: "Vercel",
      title: "Developer Advocate - Next.js",
      location: "Remote (US)",
      url: "https://vercel.com/careers",
      status: "offer" as const,
      priority: "high" as const,
      fitScore: 97,
      notes: "Received offer details package! Standard base compensation + RSU components.",
      dateOffset: -20
    },
    {
      companyName: "Netflix",
      title: "Senior UI Engineer - Growth Systems",
      location: "Los Gatos, CA",
      url: "https://jobs.netflix.com",
      status: "rejected" as const,
      priority: "medium" as const,
      fitScore: 82,
      notes: "Passed coding exam but role was filled internally. Keeping contact for future quarters.",
      dateOffset: -25
    },
    {
      companyName: "Linear",
      title: "Product Engineer",
      location: "Remote (Global)",
      url: "https://linear.app/careers",
      status: "saved" as const,
      priority: "high" as const,
      fitScore: 91,
      notes: "Need to tailor resume targeting app design details and craft a personalized cover letter.",
      dateOffset: -2
    },
    {
      companyName: "Supabase",
      title: "Developer Relations Engineer",
      location: "Remote (Global)",
      url: "https://supabase.com/careers",
      status: "ready_to_submit" as const,
      priority: "medium" as const,
      fitScore: 88,
      notes: "Form autofilled. Awaiting manual review before submission.",
      dateOffset: -4
    }
  ];

  for (const item of jobsData) {
    const jobId = generateId();
    const companyId = generateId();
    
    // Target date
    const d = new Date();
    d.setDate(d.getDate() + item.dateOffset);
    const dateStr = d.toISOString();

    const job = await saveJob({
      id: jobId,
      companyId,
      companyName: item.companyName,
      title: item.title,
      location: item.location,
      jobUrl: item.url,
      sourcePlatform: "generic"
    });

    const app = await saveApplication({
      jobId,
      companyId,
      companyName: item.companyName,
      roleTitle: item.title,
      location: item.location,
      status: item.status,
      priority: item.priority,
      fitScore: item.fitScore,
      resumeUsedId: resume.id,
      coverLetterUsedId: coverLetter.id,
      notes: item.notes,
      nextFollowUpAt: item.status === 'interviewing' ? new Date(Date.now() + 86400000 * 2).toISOString().split('T')[0] : undefined
    });

    // Write timeline activity logs
    await logActivityEvent({
      applicationId: app.id,
      jobId,
      type: "job_saved",
      message: `Saved job listing for ${item.title} at ${item.companyName}`
    });

    if (item.status !== 'saved') {
      await logActivityEvent({
        applicationId: app.id,
        jobId,
        type: "autofilled",
        message: `Autofilled form details for ${item.companyName} using profile data`
      });
    }

    if (item.status === 'submitted' || item.status === 'interviewing' || item.status === 'offer' || item.status === 'rejected') {
      await logActivityEvent({
        applicationId: app.id,
        jobId,
        type: "status_changed",
        message: `Marked application as manually submitted`
      });
    }
  }

  // 3. Seed learned answers
  const qas = [
    { q: "Are you legally authorized to work in the United States?", a: "Yes", canon: "workAuthorization", type: "select" },
    { q: "Will you now or in the future require visa sponsorship?", a: "No", canon: "sponsorship", type: "select" },
    { q: "What is your target salary compensation expectation?", a: "$140,000 - $160,000 base base salary", canon: "salaryExpectations", type: "text" },
    { q: "How many years of experience do you have with React?", a: "6", canon: "yearsExperience", type: "text" }
  ];

  for (const qa of qas) {
    await saveLearnedAnswer({
      questionText: qa.q,
      normalizedQuestion: qa.q.toLowerCase().trim(),
      fieldType: qa.type,
      answer: qa.a,
      canonicalKey: qa.canon,
      scope: "global"
    });
  }
}
