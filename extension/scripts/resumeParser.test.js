import { describe, expect, it } from 'vitest';
import { mergeParsedProfile, parseProfileFromResumeText } from './resumeParser.js';

const SAMPLE_RESUME = `Akshay Borse
425-336-9852| amsborse@gmail.com| LinkedIn | GitHub | Portfolio
PROFESSIONAL SUMMARY
Senior Software Engineer with 7+ years of experience designing large-scale distributed systems.
EXPERIENCE
Senior Software Engineer | Microsoft | Redmond, WA | Sep-2025 to Present
(C#, .NET, Azure Functions, Cosmos DB)
• Built Agent Adaptive Protection for tenant-configurable risk scoring.
Software Engineer 2 | Amazon | Seattle, WA | Aug 2019 – Aug 2025
(Java, Python, Rest, gRPC, Docker, ECS)
• Delivered high-scale backend services on AWS.
https://github.com/amsborse
https://finance-os-lilac.vercel.app/
`;

describe('resumeParser', () => {
  it('extracts contact info and latest role from resume text', () => {
    const parsed = parseProfileFromResumeText(SAMPLE_RESUME);

    expect(parsed.firstName).toBe('Akshay');
    expect(parsed.lastName).toBe('Borse');
    expect(parsed.email).toBe('amsborse@gmail.com');
    expect(parsed.phone).toBe('+1 425-336-9852');
    expect(parsed.currentTitle).toBe('Senior Software Engineer');
    expect(parsed.currentCompany).toBe('Microsoft');
    expect(parsed.location).toBe('Redmond, WA');
    expect(parsed.yearsExperience).toBe('7');
    expect(parsed.github).toBe('https://github.com/amsborse');
    expect(parsed.linkedin).toContain('linkedin.com/in/amsborse');
  });

  it('extracts work experience entries with role descriptions', () => {
    const parsed = parseProfileFromResumeText(SAMPLE_RESUME);

    expect(parsed.workExperience?.length).toBe(2);
    expect(parsed.workExperience[0].jobTitle).toBe('Senior Software Engineer');
    expect(parsed.workExperience[0].company).toBe('Microsoft');
    expect(parsed.workExperience[0].currentlyEmployed).toBe(true);
    expect(parsed.workExperience[0].startDate).toBe('09/2025');
    expect(parsed.workExperience[0].description).toContain('Agent Adaptive Protection');
    expect(parsed.workExperience[1].company).toBe('Amazon');
    expect(parsed.workExperience[1].endDate).toBe('08/2025');
    expect(parsed.workExperience[1].description).toContain('Java, Python');
  });

  it('merges parsed values into empty profile fields only by default', () => {
    const merged = mergeParsedProfile(
      { firstName: 'Akshay', email: '', phone: '' },
      { email: 'amsborse@gmail.com', phone: '+1 425-336-9852', lastName: 'Borse' }
    );

    expect(merged.firstName).toBe('Akshay');
    expect(merged.lastName).toBe('Borse');
    expect(merged.email).toBe('amsborse@gmail.com');
  });

  it('overwrites existing values when force is true', () => {
    const merged = mergeParsedProfile(
      { email: 'old@example.com' },
      { email: 'amsborse@gmail.com' },
      { force: true }
    );

    expect(merged.email).toBe('amsborse@gmail.com');
  });
});
