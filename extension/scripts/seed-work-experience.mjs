import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { parseResumeIntoDb } from './resumeParser.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dbPath = path.join(__dirname, '..', 'db.json');

const DEFAULT_WORK_EXPERIENCE = [
  {
    jobTitle: 'Senior Software Engineer',
    company: 'Microsoft',
    location: 'Redmond WA',
    currentlyEmployed: true,
    startDate: '09/2025',
    endDate: '',
    description: ''
  },
  {
    jobTitle: 'Software Engineer',
    company: 'Amazon',
    location: 'Seattle WA',
    currentlyEmployed: false,
    startDate: '08/2019',
    endDate: '08/2025',
    description: ''
  },
  {
    jobTitle: 'Software Engineering Intern',
    company: 'Liquiron',
    location: 'San Jose CA',
    currentlyEmployed: false,
    startDate: '12/2018',
    endDate: '01/2019',
    description: ''
  },
  {
    jobTitle: 'Software Engineer',
    company: 'Persistent Systems',
    location: 'Pune India',
    currentlyEmployed: false,
    startDate: '09/2016',
    endDate: '07/2017',
    description: ''
  }
];

const db = JSON.parse(fs.readFileSync(dbPath, 'utf8'));
db.profile = db.profile || {};

if (!db.profile.workExperience?.length) {
  db.profile.workExperience = DEFAULT_WORK_EXPERIENCE.map((entry) => ({ ...entry }));
  console.log('[seed] Added default work experience entries');
} else {
  console.log('[seed] workExperience already present — merging descriptions from resume');
}

const { profile, extracted } = await parseResumeIntoDb(db, { force: false });
db.profile = profile;
fs.writeFileSync(dbPath, JSON.stringify(db, null, 2));

console.log('[seed] Resume parse found', extracted.workExperience?.length || 0, 'parsed entries');
for (const entry of db.profile.workExperience || []) {
  console.log(`  - ${entry.jobTitle} @ ${entry.company} (${entry.description?.length || 0} chars description)`);
}
