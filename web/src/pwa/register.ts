/** Register the app shell service worker in production builds only. */
export async function registerServiceWorker(
  navigator: { serviceWorker?: Pick<ServiceWorkerContainer, "register"> },
  production: boolean,
): Promise<boolean> {
  if (!production || navigator.serviceWorker === undefined) return false;
  try {
    await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    return true;
  } catch {
    // The app works without it; it only loads faster and opens offline with it.
    return false;
  }
}
