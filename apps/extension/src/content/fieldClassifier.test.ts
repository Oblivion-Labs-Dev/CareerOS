import { describe, it, expect } from 'vitest';
import { normalizeQuestionText, removeCompanyNoise } from '../../src/learning/questionNormalizer';
import { stringSimilarity } from '../../src/learning/fuzzyMatcher';
import { isSensitiveField } from '../../src/learning/safetyFilters';
import { scanPage } from '../../src/content/domScanner';
import { classifyFields } from '../../src/content/fieldClassifier';
import { detectAdapter } from '../../src/adapters';
import { UserProfile } from '../../src/shared/types';

describe('JobFill Question Normalization', () => {
  it('should clean and normalize text', () => {
    expect(normalizeQuestionText('What is your name?')).toBe('what is your name');
    expect(normalizeQuestionText('Email Address!!!')).toBe('email address');
    expect(normalizeQuestionText('  Multiple   Spaces  ')).toBe('multiple spaces');
  });

  it('should remove company specific noise', () => {
    expect(removeCompanyNoise('What is your role at Oblivion Labs?', 'Oblivion Labs')).toBe('What is your role ?');
    expect(removeCompanyNoise('Do you want to work at our company?')).toBe('Do you want to work ?');
  });
});

describe('JobFill Fuzzy Matcher', () => {
  it('should calculate string similarity score', () => {
    expect(stringSimilarity('what is your name', 'what is your name')).toBe(1.0);
    expect(stringSimilarity('what is your name', 'what name')).toBeLessThan(1.0);
    expect(stringSimilarity('first name', 'last name')).toBe(0.7);
  });
});

describe('JobFill Safety Filters', () => {
  it('should identify sensitive inputs', () => {
    expect(isSensitiveField('Enter your SSN', 'ssn', '')).toBe(true);
    expect(isSensitiveField('Create a password', 'pwd', '')).toBe(true);
    expect(isSensitiveField('Credit card number', '', '')).toBe(true);
    expect(isSensitiveField('Normal field (email)', 'email', '')).toBe(false);
  });
});

describe('JobFill Classifier & DOM Scanner', () => {
  it('should classify fields based on mockup layout', async () => {
    const mockElements = [
      {
        tagName: 'INPUT',
        type: 'text',
        id: 'email-id',
        getAttribute(attr: string) {
          if (attr === 'name') return 'email';
          if (attr === 'type') return 'text';
          return null;
        },
        parentElement: {
          tagName: 'LABEL',
          textContent: 'Your Email Address',
          parentElement: null
        }
      },
      {
        tagName: 'INPUT',
        type: 'file',
        id: 'resume-file-id',
        getAttribute(attr: string) {
          if (attr === 'name') return 'resume_file';
          if (attr === 'type') return 'file';
          return null;
        },
        parentElement: null
      }
    ];

    const mockDoc = {
      querySelectorAll(selector: string) {
        if (selector.includes('input') && selector.includes('textarea') && selector.includes('select')) {
          return mockElements;
        }
        return [];
      },
      querySelector() { return null; },
      getElementById() { return null; }
    } as unknown as Document;

    const scanned = scanPage(mockDoc);
    expect(scanned.length).toBe(2);

    const profile: UserProfile = {
      firstName: 'Jane',
      lastName: 'Doe',
      fullName: 'Jane Doe',
      email: 'jane@example.com',
      phone: '123-456-7890',
      location: 'SF',
      linkedin: 'linkedin',
      github: 'github',
      portfolio: 'portfolio',
      workAuthorization: 'Yes',
      sponsorship: 'No',
      yearsExperience: '5',
      currentTitle: 'Engineer',
      targetRole: 'Senior Engineer',
      salaryExpectations: '$150k'
    };

    const classified = await classifyFields(scanned, profile);
    expect(classified.length).toBe(2);

    const emailField = classified.find((c) => c.canonicalKey === 'email');
    expect(emailField).toBeDefined();
    expect(emailField?.proposedValue).toBe('jane@example.com');

    const resumeField = classified.find((c) => c.canonicalKey === 'resume');
    expect(resumeField).toBeDefined();
    expect(resumeField?.confidence).toBe('high');
  });
});
