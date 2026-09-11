import { flushSync } from "react-dom";
export const identityTransition = (id: string) => `company-${Array.from(id).map(c => c.codePointAt(0)!.toString(16)).join("-")}`;
export function transitionSurface(update: () => void) {
  const doc = document as Document & { startViewTransition?: (callback: () => void) => unknown };
  if (!doc.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches || doc.documentElement.dataset.motion === "paused") {update(); return;}
  doc.startViewTransition(() => flushSync(update));
}
