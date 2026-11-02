/** Per-frame probe for unreachable iframes. */
export const FRAME_PROBE_TIMEOUT_MS = 1_500;

/** Max time to wait for autofill in a single frame. */
export const FRAME_AUTOFILL_TIMEOUT_MS = 125_000;

/** Max time to wait for a scan response from a single frame. */
export const FRAME_SCAN_TIMEOUT_MS = 8_000;

/** Content script: hard cap for runFullPageAutofill (must be under frame timeout). */
export const CONTENT_AUTOFILL_TIMEOUT_MS = 120_000;

/** Floating widget: profile fetch from background. */
export const WIDGET_PROFILE_TIMEOUT_MS = 8_000;

/** Floating widget: multi-frame scan. */
export const WIDGET_SCAN_TIMEOUT_MS = 12_000;

/** Floating widget: autofill execution after scan. */
export const WIDGET_AUTOFILL_TIMEOUT_MS = 122_000;

/** Floating widget: hard cap for the entire fill flow. */
export const WIDGET_OPERATION_TIMEOUT_MS = 100_000;

/** Popup autofill: background round-trip cap. */
export const POPUP_AUTOFILL_TIMEOUT_MS = 90_000;

export const WIDGET_ERROR_DISPLAY_MS = 8_000;
export const WIDGET_WARNING_DISPLAY_MS = 12_000;
export const WIDGET_SUCCESS_DISPLAY_MS = 2_800;
