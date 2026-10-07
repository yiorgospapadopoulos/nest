// The message the service worker sends an open window when a notification is tapped.
// The worker keeps its own copy of the name (see serviceWorker.ts): it is built as a
// classic script, so it must share no module with the app.

export const NAVIGATE = "harness:navigate";

export interface NavigateMessage {
  type: typeof NAVIGATE;
  url: string;
}
