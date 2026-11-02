import { UserProfile, JobDetails } from './types';

export interface ScanPageMessage {
  action: 'scan';
}

export interface AutofillPageMessage {
  action: 'autofill';
  profile: UserProfile;
}

export interface HighlightFieldsMessage {
  action: 'highlight';
  enabled: boolean;
}

export type ExtensionMessage =
  | ScanPageMessage
  | AutofillPageMessage
  | HighlightFieldsMessage;
