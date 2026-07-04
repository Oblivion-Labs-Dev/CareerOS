import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dbPath = path.join(__dirname, '..', 'db.json');

const SCREENING_ANSWERS = [
  {
    id: 'us-work-authorization',
    question: 'Are you authorized to work in the U.S.?',
    answer: 'Yes',
    matchPatterns: ['authorized to work in the us', 'authorized to work in the united states']
  },
  {
    id: 'spouse-visa-status',
    question:
      'Is your current U.S. work authorization based on your status as a spouse of an H-1B, L-1, or E-1/E-2/E-3 visa holder?',
    answer: 'No',
    matchPatterns: ['spouse of an h-1b', 'spouse of an h1b', 'e-1/e-2/e-3 visa holder']
  },
  {
    id: 'visa-sponsorship-needed',
    question:
      'Will you need Snap to sponsor you for a visa to work legally in the United States, now or in the future?',
    answer: 'Yes',
    matchPatterns: ['need.*sponsor you for a visa', 'visa sponsorship', 'sponsor you for a visa']
  },
  {
    id: 'snap-eligibility-followup',
    question: 'Did you answer "no" to Question 1 and/or "yes" to question 2 or 3?',
    answer: 'No',
    matchPatterns: ['answered no to question 1', 'yes to question 2 or 3']
  },
  {
    id: 'relocate-to-job-location',
    question:
      'Do you currently live in or are you able to relocate to the location this job is advertised in?',
    answer: 'Yes',
    matchPatterns: ['relocate to the location', 'live in or are you able to relocate']
  },
  {
    id: 'office-attendance-commitment',
    question:
      'Are you able to commit to coming into the office as advertised on the job description?',
    answer: 'Yes',
    matchPatterns: ['commit to coming into the office', '4+ days a week']
  },
  {
    id: 'meets-minimum-experience',
    question:
      'Can you confirm that you meet the minimum qualification for years of professional work experience for this role?',
    answer: 'Yes',
    matchPatterns: ['meet the minimum qualification', 'minimum qualification for years']
  },
  {
    id: 'big-four-employment',
    question: 'Are you a current or former (prior 18 months) employee of EY, PwC, Deloitte or KPMG?',
    answer: 'No',
    matchPatterns: ['employee of ey', 'pwc', 'deloitte', 'kpmg']
  }
];

const db = JSON.parse(fs.readFileSync(dbPath, 'utf8'));
db.profile = db.profile || {};
db.profile.screeningAnswers = SCREENING_ANSWERS;
db.profile.workAuthorization = 'Yes';
db.profile.sponsorship = 'Yes';

fs.writeFileSync(dbPath, JSON.stringify(db, null, 2));
console.log('[seed] Saved', SCREENING_ANSWERS.length, 'screening answers to profile');
