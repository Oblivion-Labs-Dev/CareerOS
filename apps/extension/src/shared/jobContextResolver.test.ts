import { describe, expect, it } from 'vitest';
import {
  enrichJobDetails,
  parseFromDocumentTitle,
  parseRoleFromWorkdayUrl,
  resolveJobContext
} from './jobContextResolver';
import { parseCompanyFromJobUrl } from './jobUrlMatching';

describe('parseCompanyFromJobUrl', () => {
  it('parses Workday recruiting slug', () => {
    expect(
      parseCompanyFromJobUrl(
        'https://wd1.myworkdaysite.com/en-US/recruiting/snapchat/snap/job/Los-Angeles/Software-Engineer_Q326SWEB6-1/apply/autofillWithResume'
      )
    ).toBe('Snapchat');
  });

  it('parses Greenhouse board slug', () => {
    expect(parseCompanyFromJobUrl('https://job-boards.greenhouse.io/thetradedesk/jobs/5057572007/confirmation')).toBe(
      'Thetradedesk'
    );
  });

  it('parses Ashby board slug', () => {
    expect(parseCompanyFromJobUrl('https://jobs.ashbyhq.com/openai/abc123/application')).toBe('Openai');
  });
});

describe('parseFromDocumentTitle', () => {
  it('parses role at company', () => {
    expect(parseFromDocumentTitle('Software Engineer at Snapchat')).toEqual({
      role: 'Software Engineer',
      company: 'Snapchat'
    });
  });

  it('parses role before company with dash', () => {
    expect(parseFromDocumentTitle('Software Engineer, Backend, Level 5 - Snapchat')).toEqual({
      role: 'Software Engineer, Backend, Level 5',
      company: 'Snapchat'
    });
  });
});

describe('parseRoleFromWorkdayUrl', () => {
  it('parses role slug from Workday job path', () => {
    expect(
      parseRoleFromWorkdayUrl(
        'https://wd1.myworkdaysite.com/en-US/recruiting/snapchat/snap/job/Los-Angeles%2C-California/Software-Engineer--Backend--Level-5_Q326SWEB6-1/apply/autofillWithResume'
      )
    ).toBe('Software Engineer Backend Level 5 Q326SWEB6 1');
  });
});

describe('enrichJobDetails', () => {
  it('fills unknown company from tab url', () => {
    const enriched = enrichJobDetails(
      { company: 'Unknown Company', role: 'Software Engineer', location: '', description: '', platform: 'Generic' },
      'https://wd1.myworkdaysite.com/en-US/recruiting/snapchat/snap/job/foo/apply/autofillWithResume',
      'Software Engineer, Backend, Level 5'
    );
    expect(enriched.company).toBe('Snapchat');
  });
});

describe('resolveJobContext', () => {
  it('uses url fallback when adapter returns unknown company', () => {
    const doc = {
      title: 'Software Engineer, Backend, Level 5',
      location: { href: 'https://wd1.myworkdaysite.com/en-US/recruiting/snapchat/snap/job/foo/Bar/apply', search: '' },
      querySelector: () => null,
      querySelectorAll: () => [],
      body: { innerText: '' }
    } as unknown as Document;

    const context = resolveJobContext(doc);
    expect(context.company).toBe('Snapchat');
  });

  it('prefers OpenAI over Ashby Client on embedded Ashby pages', () => {
    const doc = {
      title: 'Software Engineer, API SDK',
      location: { href: 'https://jobs.ashbyhq.com/openai/abc123/application', search: '', hostname: 'jobs.ashbyhq.com' },
      querySelector: (selector: string) => {
        if (selector.includes('header img[alt]')) {
          return { getAttribute: () => 'OpenAI' };
        }
        if (selector === 'h1') {
          return { textContent: 'Software Engineer, API SDK' };
        }
        return null;
      },
      querySelectorAll: () => [],
      body: { innerText: '' }
    } as unknown as Document;

    const context = resolveJobContext(doc);
    expect(context.company).not.toBe('Ashby Client');
    expect(context.company).toBe('Openai');
  });
});
