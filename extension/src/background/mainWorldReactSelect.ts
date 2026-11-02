/**
 * Self-contained function injected into the page MAIN world via chrome.scripting.executeScript.
 * Must not close over module scope — Chrome serializes this function body only.
 */
export async function mainWorldFillReactSelect(inputId: string, value: string): Promise<boolean> {
  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
  const norm = (text: string) => text.replace(/\s+/g, ' ').trim().toLowerCase();

  function expandFillTargets(raw: string): string[] {
    const targets = [raw.trim()];
    if (/^none$/i.test(raw.trim()) || /^n\/a/i.test(raw.trim()) || /never held/i.test(raw.trim())) {
      targets.push(
        'N/A - have never held U.S. security clearance',
        'I have never held a U.S. security clearance',
        'Not applicable'
      );
    }
    if (/none of the above/i.test(raw) || /not a protected individual/i.test(raw)) {
      targets.push('None of the above');
    }
    return [...new Set(targets.filter(Boolean))];
  }

  function scoreOption(option: string, target: string): number {
    const optionNorm = norm(option);
    const targetNorm = norm(target);
    if (!optionNorm || !targetNorm) return 0;
    if (optionNorm === targetNorm) return 100;
    if (optionNorm.includes(targetNorm) || targetNorm.includes(optionNorm)) return 85;
    if (/^(yes|no)$/i.test(targetNorm) && optionNorm.startsWith(targetNorm)) return 90;
    return 0;
  }

  function readDisplay(input: HTMLInputElement): string {
    const shell = input.closest('.select-shell');
    const single = shell?.querySelector('.select__single-value, [class*="single-value"]');
    const text = single?.textContent?.replace(/\s+/g, ' ').trim() || '';
    if (text && !/^(select\.\.\.|select|choose)$/i.test(text)) return text;
    return '';
  }

  function isCommitted(input: HTMLInputElement, expected?: string): boolean {
    const display = readDisplay(input);
    if (!display) return false;
    if (!expected?.trim()) return true;
    return scoreOption(display, expected) >= 75;
  }

  const input = document.getElementById(inputId) as HTMLInputElement | null;
  if (!input) return false;
  const fillTargets = expandFillTargets(value);

  for (const targetValue of fillTargets) {
    if (isCommitted(input, targetValue)) return true;
  }

  const shell = input.closest('.select-shell');
  const control = shell?.querySelector('.select__control') as HTMLElement | null;

  for (let attempt = 0; attempt < 5; attempt++) {
    input.focus();
    control?.click();
    input.click();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    await sleep(160);

    const options = Array.from(
      document.querySelectorAll(
        '.select__menu [role="option"], .select__menu .select__option, [class*="select__menu"] [class*="select__option"]'
      )
    ) as HTMLElement[];

    for (const targetValue of fillTargets) {
      let best: HTMLElement | null = null;
      let bestScore = 0;
      for (const option of options) {
        const label = option.textContent?.replace(/\s+/g, ' ').trim() || '';
        if (!label || /^select\.\.\.$/i.test(label)) continue;
        const score = scoreOption(label, targetValue);
        if (score > bestScore) {
          bestScore = score;
          best = option;
        }
      }

      if (best && bestScore >= 75) {
        best.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
        best.click();
        await sleep(120);
        if (fillTargets.some((target) => isCommitted(input, target))) return true;
      }

      if (/^(yes|no)$/i.test(targetValue.trim())) {
        const target = norm(targetValue);
        const index = options.findIndex((option) => norm(option.textContent || '').startsWith(target));
        const steps = index >= 0 ? index + 1 : 1;
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
        for (let step = 1; step < steps; step++) {
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
          await sleep(40);
        }
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        await sleep(120);
        if (fillTargets.some((target) => isCommitted(input, target))) return true;
      }
    }

    await sleep(100);
  }

  return fillTargets.some((target) => isCommitted(input, target));
}

export async function fillReactSelectInMainWorld(
  tabId: number,
  frameId: number,
  inputId: string,
  value: string
): Promise<boolean> {
  if (!inputId?.trim() || !value?.trim()) return false;
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId, frameIds: [frameId] },
      world: 'MAIN',
      func: mainWorldFillReactSelect,
      args: [inputId, value]
    });
    return Boolean(result?.result);
  } catch {
    return false;
  }
}
