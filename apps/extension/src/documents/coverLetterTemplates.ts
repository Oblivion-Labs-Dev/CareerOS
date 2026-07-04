export interface CoverLetterReplacements {
  company: string;
  role: string;
  candidateName: string;
  topSkills: string;
  experienceSummary: string;
  [key: string]: string;
}

export interface CoverLetterProvider {
  generate(template: string, variables: CoverLetterReplacements): Promise<string>;
}

/**
 * Local Template Provider that substitutes placeholders inside a template body.
 */
export class LocalTemplateProvider implements CoverLetterProvider {
  async generate(template: string, variables: CoverLetterReplacements): Promise<string> {
    if (!template || typeof template !== 'string') return '';
    let result = template;
    for (const [key, val] of Object.entries(variables)) {
      const placeholder = new RegExp(`{{\\s*${key}\\s*}}`, 'g');
      result = result.replace(placeholder, val || '');
    }
    return result;
  }
}

/**
 * Compiles a cover letter using the local template engine
 */
export async function compileCoverLetter(
  templateBody: string,
  replacements: CoverLetterReplacements
): Promise<string> {
  const provider = new LocalTemplateProvider();
  return await provider.generate(templateBody, replacements);
}
