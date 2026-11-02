export const SCAN_MESSAGES = [
  'Reading the form…',
  'Finding field labels…',
  'Matching your profile…',
  'Almost there…'
];

export const AUTOFILL_MESSAGES = [
  'Filling contact info…',
  'Attaching your resume…',
  'Working through dropdowns…',
  'Dotting the i\'s…',
  'Saving you clicks…'
];

export function cycleMessages(
  messages: string[],
  onTick: (message: string, index: number) => void,
  intervalMs = 900
): () => void {
  let index = 0;
  onTick(messages[0], 0);
  const id = window.setInterval(() => {
    index = (index + 1) % messages.length;
    onTick(messages[index], index);
  }, intervalMs);
  return () => window.clearInterval(id);
}
