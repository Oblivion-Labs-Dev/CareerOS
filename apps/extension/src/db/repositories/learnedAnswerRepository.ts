import { runInStore } from '../db';
import { generateId } from '../../shared/id';
import { getCurrentDateTimeISO } from '../../shared/dateUtils';
import { LearnedAnswer } from '../../shared/learningTypes';
import { normalizeQuestionText } from '../../learning/questionNormalizer';

let memoryCache: LearnedAnswer[] = [];

export async function getLearnedAnswers(): Promise<LearnedAnswer[]> {
  if (typeof indexedDB === 'undefined') return memoryCache;
  try {
    return await runInStore<LearnedAnswer[]>('learnedAnswers', 'readonly', (store) => store.getAll());
  } catch {
    return memoryCache;
  }
}

export async function saveLearnedAnswer(
  answerData: Omit<LearnedAnswer, 'id' | 'createdAt' | 'updatedAt' | 'usageCount' | 'confidenceBoost' | 'disabled' | 'rejectedCount'> & { id?: string; confidenceBoost?: number; disabled?: boolean; rejectedCount?: number }
): Promise<LearnedAnswer> {
  const questionText = typeof answerData.questionText === 'string' ? answerData.questionText.trim() : '';
  const normalizedQuestion =
    typeof answerData.normalizedQuestion === 'string' && answerData.normalizedQuestion
      ? answerData.normalizedQuestion
      : normalizeQuestionText(questionText);

  const list = await getLearnedAnswers();
  const now = getCurrentDateTimeISO();

  let existing = answerData.id
    ? list.find(a => a.id === answerData.id)
    : list.find(a => a.questionText === questionText);

  if (existing) {
    existing.questionText = questionText || existing.questionText;
    existing.normalizedQuestion = normalizedQuestion || existing.normalizedQuestion;
    existing.answer = answerData.answer;
    existing.scope = answerData.scope;
    existing.company = answerData.company;
    existing.domain = answerData.domain;
    existing.updatedAt = now;
    existing.disabled = answerData.disabled !== undefined ? answerData.disabled : existing.disabled;
  } else {
    existing = {
      id: answerData.id || generateId(),
      questionText,
      normalizedQuestion,
      fieldType: answerData.fieldType,
      options: answerData.options,
      answer: answerData.answer,
      canonicalKey: answerData.canonicalKey,
      scope: answerData.scope,
      company: answerData.company,
      domain: answerData.domain,
      confidenceBoost: answerData.confidenceBoost || 1.0,
      createdAt: now,
      updatedAt: now,
      usageCount: 0,
      rejectedCount: answerData.rejectedCount || 0,
      disabled: answerData.disabled || false
    };
    list.push(existing);
  }

  if (typeof indexedDB === 'undefined') {
    memoryCache = list;
  } else {
    try {
      const item = { ...existing };
      await runInStore<void>('learnedAnswers', 'readwrite', (store) => store.put(item));
    } catch {
      memoryCache = list;
    }
  }
  return existing;
}

export async function deleteLearnedAnswer(id: string): Promise<void> {
  const list = await getLearnedAnswers();
  const filtered = list.filter(a => a.id !== id);
  memoryCache = filtered;

  if (typeof indexedDB !== 'undefined') {
    try {
      await runInStore<void>('learnedAnswers', 'readwrite', (store) => store.delete(id));
    } catch {
      // Ignored
    }
  }
}
