import { normalizeQuestionText, removeCompanyNoise } from './questionNormalizer';
import { stringSimilarity } from './fuzzyMatcher';
import { getLearnedAnswers, saveLearnedAnswer, incrementUsage, adjustConfidence } from './learnedAnswerStore';
import { LearnedAnswer, MatchResult, LearnedAnswerScope } from '../shared/learningTypes';
import { isSensitiveField } from './safetyFilters';

/**
 * Searches the learned answers for a matching question
 */
export async function matchQuestion(
  questionText: string,
  fieldType: string,
  options?: string[],
  company?: string,
  domain?: string
): Promise<MatchResult | null> {
  if (!questionText || typeof questionText !== 'string') return null;
  const normalizedInput = normalizeQuestionText(removeCompanyNoise(questionText, company));

  if (!normalizedInput) return null;

  const answers = await getLearnedAnswers();
  let bestMatch: LearnedAnswer | null = null;
  let bestScore = 0;

  for (const answer of answers) {
    if (!answer.normalizedQuestion) continue;
    // 1. Skip if field types are incompatible
    if (answer.fieldType !== fieldType) continue;

    // 2. Check scope restrictions
    if (answer.scope === 'company' && answer.company !== company) continue;
    if (answer.scope === 'domain' && answer.domain !== domain) continue;

    // 3. Compute base similarity score
    let score = stringSimilarity(normalizedInput, answer.normalizedQuestion);

    // 4. Boost score if options list matches exactly
    if (options && answer.options) {
      const optionsMatch =
        options.length === answer.options.length &&
        options.every((opt) => answer.options?.includes(opt));
      if (optionsMatch) {
        score = Math.min(score + 0.15, 1.0);
      }
    }

    // 5. Factor in confidence booster
    const weightedScore = score * answer.confidenceBoost;

    if (weightedScore > bestScore) {
      bestScore = weightedScore;
      bestMatch = answer;
    }
  }

  if (!bestMatch || bestScore < 0.4) {
    return null;
  }

  let confidence: 'high' | 'medium' | 'low' = 'low';
  if (bestScore >= 0.85) {
    confidence = 'high';
  } else if (bestScore >= 0.6) {
    confidence = 'medium';
  }

  return {
    learnedAnswer: bestMatch,
    score: bestScore,
    confidence
  };
}

/**
 * Teaches JobFill a new question/answer pair
 */
export async function learnAnswer(params: {
  questionText: string;
  fieldType: string;
  answer: string;
  options?: string[];
  canonicalKey?: string;
  scope: LearnedAnswerScope;
  company?: string;
  domain?: string;
}): Promise<LearnedAnswer | null> {
  const questionText = typeof params.questionText === 'string' ? params.questionText.trim() : '';
  if (!questionText) {
    return null;
  }

  // Safety first: never learn sensitive fields
  if (isSensitiveField(questionText, params.canonicalKey || '', '')) {
    console.warn('Blocked learning sensitive field:', questionText);
    return null;
  }

  const normalized = normalizeQuestionText(removeCompanyNoise(questionText, params.company));

  return await saveLearnedAnswer({
    questionText,
    normalizedQuestion: normalized,
    fieldType: params.fieldType,
    options: params.options,
    answer: params.answer,
    canonicalKey: params.canonicalKey,
    scope: params.scope,
    company: params.company,
    domain: params.domain
  });
}

/**
 * Confirms usage of a learned answer (increases usage statistics)
 */
export async function confirmUsage(id: string): Promise<void> {
  await incrementUsage(id);
}

/**
 * Modifies confidence values based on user feedback
 */
export async function registerFeedback(id: string, approved: boolean): Promise<void> {
  const delta = approved ? 0.05 : -0.2; // Penalize rejections heavily, reward approvals gently
  await adjustConfidence(id, delta);
}
