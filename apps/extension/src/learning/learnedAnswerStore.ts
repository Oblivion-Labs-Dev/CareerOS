import { LearnedAnswer } from '../shared/learningTypes';
import {
  getLearnedAnswers as dbGetLearnedAnswers,
  saveLearnedAnswer as dbSaveLearnedAnswer,
  deleteLearnedAnswer as dbDeleteLearnedAnswer
} from '../db/repositories/learnedAnswerRepository';

export async function getLearnedAnswers(): Promise<LearnedAnswer[]> {
  return await dbGetLearnedAnswers();
}

export async function saveLearnedAnswer(
  answerData: Omit<LearnedAnswer, 'id' | 'createdAt' | 'updatedAt' | 'usageCount' | 'confidenceBoost'> & { id?: string }
): Promise<LearnedAnswer> {
  return await dbSaveLearnedAnswer(answerData);
}

export async function deleteLearnedAnswer(id: string): Promise<void> {
  await dbDeleteLearnedAnswer(id);
}

export async function incrementUsage(id: string): Promise<void> {
  const answers = await dbGetLearnedAnswers();
  const item = answers.find((a) => a.id === id);
  if (item) {
    const updated = {
      ...item,
      usageCount: item.usageCount + 1,
      lastUsedAt: new Date().toISOString(),
      confidenceBoost: Math.min(item.confidenceBoost + 0.1, 2.0)
    };
    await dbSaveLearnedAnswer(updated);
  }
}

export async function adjustConfidence(id: string, delta: number): Promise<void> {
  const answers = await dbGetLearnedAnswers();
  const item = answers.find((a) => a.id === id);
  if (item) {
    const updated = {
      ...item,
      confidenceBoost: Math.max(0.1, Math.min(item.confidenceBoost + delta, 2.0))
    };
    await dbSaveLearnedAnswer(updated);
  }
}
