export type LearnedAnswerScope = 'global' | 'company' | 'domain' | 'oneTime';

export interface LearnedAnswer {
  id: string;
  questionText: string;
  normalizedQuestion: string;
  fieldType: string;
  options?: string[];
  answer: string;
  canonicalKey?: string;
  scope: LearnedAnswerScope;
  company?: string;
  domain?: string;
  confidenceBoost: number; // starts at 1, increases with reuse, decreases with rejection
  createdAt: string;
  updatedAt: string;
  usageCount: number;
  lastUsedAt?: string;
}

export interface MatchResult {
  learnedAnswer: LearnedAnswer;
  score: number; // 0 to 1
  confidence: 'high' | 'medium' | 'low';
}
