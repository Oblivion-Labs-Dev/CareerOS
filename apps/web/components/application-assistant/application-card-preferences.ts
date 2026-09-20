export type ApplicationCardStyle = "compact" | "heritage" | "holographic" | "clay";

export const APPLICATION_CARD_STYLE_KEY = "careeros.application-card-style";
export const APPLICATION_CARD_STYLE_EVENT = "careeros:application-card-style";

const STYLES: ApplicationCardStyle[] = ["compact", "heritage", "holographic", "clay"];

function isStyle(value: string | null): value is ApplicationCardStyle {
  return value !== null && (STYLES as string[]).includes(value);
}

export function readApplicationCardStyle(): ApplicationCardStyle {
  if (typeof window === "undefined") return "compact";
  const style = window.localStorage.getItem(APPLICATION_CARD_STYLE_KEY);
  return isStyle(style) ? style : "compact";
}

/** Mirror the choice onto <html> so a style can also dress the page around the
 *  cards. Clay needs that: a pale, soft-lit ground is half of what makes a clay
 *  surface read as clay, and a card cannot paint the page it sits on. */
export function applyApplicationCardStyleAttribute(style: ApplicationCardStyle) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.cardStyle = style;
}

export function saveApplicationCardStyle(style: ApplicationCardStyle) {
  window.localStorage.setItem(APPLICATION_CARD_STYLE_KEY, style);
  applyApplicationCardStyleAttribute(style);
  window.dispatchEvent(new Event(APPLICATION_CARD_STYLE_EVENT));
}
