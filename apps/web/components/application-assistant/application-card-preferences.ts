export type ApplicationCardStyle = "compact" | "heritage" | "holographic";

export const APPLICATION_CARD_STYLE_KEY = "careeros.application-card-style";
export const APPLICATION_CARD_STYLE_EVENT = "careeros:application-card-style";

export function readApplicationCardStyle(): ApplicationCardStyle {
  if (typeof window === "undefined") return "compact";
  const style = window.localStorage.getItem(APPLICATION_CARD_STYLE_KEY);
  return style === "heritage" || style === "holographic" ? style : "compact";
}

export function saveApplicationCardStyle(style: ApplicationCardStyle) {
  window.localStorage.setItem(APPLICATION_CARD_STYLE_KEY, style);
  window.dispatchEvent(new Event(APPLICATION_CARD_STYLE_EVENT));
}
