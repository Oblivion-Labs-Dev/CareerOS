export interface FloatingWidgetConfig {
  /** When false, the floating AP/autofill panel is hidden on job pages. Popup autofill still works. */
  enabled: boolean;
}

export const DEFAULT_FLOATING_WIDGET_CONFIG: FloatingWidgetConfig = {
  enabled: true,
};

const STORAGE_KEY = 'floatingWidgetConfig';

let cachedConfig: FloatingWidgetConfig | null = null;

export function mergeFloatingWidgetConfig(
  partial?: Partial<FloatingWidgetConfig> | null
): FloatingWidgetConfig {
  return { ...DEFAULT_FLOATING_WIDGET_CONFIG, ...partial };
}

export async function getFloatingWidgetConfig(): Promise<FloatingWidgetConfig> {
  if (cachedConfig) return cachedConfig;

  try {
    const stored = await chrome.storage.local.get(STORAGE_KEY);
    cachedConfig = mergeFloatingWidgetConfig(stored[STORAGE_KEY] as Partial<FloatingWidgetConfig>);
  } catch {
    cachedConfig = { ...DEFAULT_FLOATING_WIDGET_CONFIG };
  }

  return cachedConfig;
}

export function setFloatingWidgetConfig(config: Partial<FloatingWidgetConfig>): void {
  cachedConfig = mergeFloatingWidgetConfig(config);
  void chrome.storage.local.set({ [STORAGE_KEY]: cachedConfig });
}

export function invalidateFloatingWidgetConfigCache(): void {
  cachedConfig = null;
}

export function removeFloatingWidgetFromDom(doc: Document = document): void {
  doc.getElementById('jobfill-floating-wrapper')?.remove();
  doc.getElementById('jobfill-widget-styles')?.remove();
}
