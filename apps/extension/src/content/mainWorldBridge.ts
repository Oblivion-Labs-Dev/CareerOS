/** Ask the background service worker to run a trusted MAIN-world React Select fill. */
export function fillReactSelectInMainWorld(inputId: string, value: string): Promise<boolean> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      { action: 'main-world-fill-react-select', inputId, value },
      (response: { success?: boolean } | undefined) => {
        if (chrome.runtime.lastError) {
          resolve(false);
          return;
        }
        resolve(Boolean(response?.success));
      }
    );
  });
}
