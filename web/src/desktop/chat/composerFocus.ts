// A composer asked to take the keyboard, as the Mac's draft.wantsFocus: after Edit puts
// a message back, a sheet over it closes, or the palette opens its chat. Keyed by the
// draft's key.
const listeners = new Map<string, Set<() => void>>();
// Asked before its composer was there, as a chat the palette opens in a new pane: the
// composer takes the keyboard as it mounts (B147).
const waiting = new Set<string>();

export function focusComposer(key: string): void {
  // After any sheet closed and gave the focus back to what opened it.
  window.setTimeout(() => {
    const set = listeners.get(key);
    if (set === undefined || set.size === 0) {
      waiting.add(key);
      return;
    }
    for (const listener of [...set]) listener();
  }, 0);
}

export function onComposerFocus(key: string, listener: () => void): () => void {
  const set = listeners.get(key) ?? new Set();
  set.add(listener);
  listeners.set(key, set);
  if (waiting.delete(key)) window.setTimeout(listener, 0);
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
