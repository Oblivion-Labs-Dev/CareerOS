/**
 * Card-to-dialog flip. The dialog starts exactly over the card that opened
 * it, showing a live copy of that card on its back face, then travels to the
 * centre while growing and turning over to show its content: one continuous
 * movement. Closing plays the same path in reverse, back into the card.
 *
 * Pure DOM + Web Animations, so it needs no layout library and runs on the
 * compositor (transform and opacity only).
 */

export const FLIP_MS = 620;
const EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)";
const PERSPECTIVE = "perspective(1800px)";

const reducedMotion = () =>
  typeof window !== "undefined" && !!window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Transform that lays the dialog over `origin`, flipped to show its back face. */
function originTransform(dialog: DOMRect, origin: DOMRect) {
  const dx = origin.left + origin.width / 2 - (dialog.left + dialog.width / 2);
  const dy = origin.top + origin.height / 2 - (dialog.top + dialog.height / 2);
  const sx = origin.width / dialog.width;
  const sy = origin.height / dialog.height;
  return {
    sx,
    sy,
    from: `${PERSPECTIVE} translate(${dx}px, ${dy}px) scale(${sx}, ${sy}) rotateY(180deg)`,
    to: `${PERSPECTIVE} translate(0px, 0px) scale(1, 1) rotateY(0deg)`,
  };
}

/** Put a copy of the card on the dialog's back face, sized so it lines up exactly at the start. */
function dressCover(cover: HTMLElement, origin: HTMLElement, originRect: DOMRect, sx: number, sy: number) {
  const clone = origin.cloneNode(true) as HTMLElement;
  for (const el of [clone, ...clone.querySelectorAll<HTMLElement>("[id],[data-job-id],[data-card-variant],[tabindex]")]) {
    el.removeAttribute("id");
    el.removeAttribute("data-job-id");
    el.removeAttribute("data-card-variant");
    el.removeAttribute("tabindex");
    el.removeAttribute("role");
  }
  clone.style.cssText += `;position:absolute;left:0;top:0;margin:0;width:${originRect.width}px;height:${originRect.height}px;transform:scale(${1 / sx}, ${1 / sy});transform-origin:0 0;animation:none;translate:none;`;
  cover.replaceChildren(clone);
}

type Run = { animation: Animation; restore: () => void };

/**
 * Animate `dialog` in from `origin` (or out, when `reverse`). Returns null when
 * nothing was animated. The origin card is hidden while the dialog is "made
 * of" it, so there are never two copies on screen.
 */
export function runFlip(dialog: HTMLElement, origin: HTMLElement | null, reverse: boolean): Run | null {
  if (typeof dialog.animate !== "function") return null;
  const timing = (duration: number): KeyframeAnimationOptions => ({ duration, easing: EASE, fill: "both", direction: reverse ? "reverse" : "normal" });

  if (reducedMotion()) {
    return { animation: dialog.animate([{ opacity: 0 }, { opacity: 1 }], timing(160)), restore: () => {} };
  }
  const originRect = origin?.isConnected ? origin.getBoundingClientRect() : null;
  if (!origin || !originRect || originRect.width === 0) {
    const animation = dialog.animate(
      [{ opacity: 0, transform: "scale(0.96)" }, { opacity: 1, transform: "none" }],
      timing(260),
    );
    return { animation, restore: () => {} };
  }

  const dialogRect = dialog.getBoundingClientRect();
  const { from, to, sx, sy } = originTransform(dialogRect, originRect);
  const cover = dialog.querySelector<HTMLElement>("[data-flip-cover]");
  if (cover) dressCover(cover, origin, originRect, sx, sy);

  const previousVisibility = origin.style.visibility;
  origin.style.visibility = "hidden";
  const animation = dialog.animate([{ transform: from }, { transform: to }], timing(FLIP_MS));
  const restore = () => {
    origin.style.visibility = previousVisibility;
  };
  // Opening: the dialog now covers the card, so it can come back underneath.
  // Closing: it comes back once the dialog has landed on it.
  animation.finished.then(restore, restore);
  // A finished opening drops its fill, so the open dialog carries no 3D
  // transform at all and its text renders as crisp as any other page.
  if (!reverse) animation.finished.then(() => animation.cancel(), () => {});
  return { animation, restore };
}
