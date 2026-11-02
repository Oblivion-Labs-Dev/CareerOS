export interface FileAttachment {
  name: string;
  type: string;
  base64: string;
}

export interface WorkExperienceEntry {
  jobTitle: string;
  company: string;
  location: string;
  currentlyEmployed: boolean;
  /** MM/YYYY for Workday date fields */
  startDate: string;
  endDate?: string;
  /** Role description — populated from resume parse when available */
  description: string;
}

export interface ScreeningAnswer {
  id: string;
  question: string;
  answer: string;
  /** Optional regex fragments to match question labels on ATS forms */
  matchPatterns?: string[];
}

export interface UserProfile {
  firstName: string;
  lastName: string;
  fullName: string;
  preferredName?: string;
  email: string;
  phone: string;
  phoneCountryCode?: string;
  location: string;
  linkedin: string;
  github: string;
  portfolio: string;
  workAuthorization: string; // "Yes" / "No"
  sponsorship: string; // "Yes" / "No"
  yearsExperience: string;
  currentTitle: string;
  targetRole: string;
  salaryExpectations: string;
  summary?: string;
  skills?: string[];
  currentCompany?: string;
  pronouns?: string;
  gender?: string;
  transgender?: string;
  sexualOrientation?: string;
  raceEthnicity?: string;
  hispanic?: string;
  veteran?: string;
  disability?: string;
  smsConsent?: string;
  customFields?: Record<string, string>;
  workExperience?: WorkExperienceEntry[];
  screeningAnswers?: ScreeningAnswer[];
  resume?: FileAttachment;
  coverLetter?: FileAttachment;
}

export type ApplicationStatus =
  | 'viewed'
  | 'autofilled'
  | 'readyToSubmit'
  | 'submittedManually'
  | 'rejected'
  | 'interview';

export interface ApplicationRecord {
  id: string;
  company: string;
  role: string;
  url: string;
  date: string;
  status: ApplicationStatus;
  resumeUsed?: string;
  coverLetterUsed?: string;
  notes?: string;
}

export interface JobDetails {
  company: string;
  role: string;
  location: string;
  description: string;
  platform: string;
}
