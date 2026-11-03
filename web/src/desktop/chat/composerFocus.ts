// A composer asked to take the keyboard, as the Mac's draft.wantsFocus: after Edit puts
// a message back, or a sheet over it closes. Keyed by the draft's key.
const listeners = new Map<string, Set<() => void>>();

export function focusComposer(key: string): void {
  // After any sheet closed and gave the focus back to what opened it.
  window.setTimeout(() => {
    for (const listener of [...(listeners.get(key) ?? [])]) listener();
  }, 0);
}

export function onComposerFocus(key: string, listener: () => void): () => void {
  const set = listeners.get(key) ?? new Set();
  set.add(listener);
  listeners.set(key, set);
  return () => {
    set.delete(listener);
  };
}

// Esc Esc in a composer: its chat's transcript rewinds to before the last message (B59).
const rewinds = new Map<string, Set<() => void>>();

export function askRewindLast(chat: string): void {
  for (const listener of [...(rewinds.get(chat) ?? [])]) listener();
}

export function onRewindLast(chat: string, listener: () => void): () => void {
  const set = rewinds.get(chat) ?? new Set();
  set.add(listener);
  rewinds.set(chat, set);
  return () => {
    set.delete(listener);
  };
}
