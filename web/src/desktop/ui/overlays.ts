// The open menus and popovers, newest last, so the window's Escape and Ctrl+W close the
// topmost one before anything under it (the Mac's closeFocused closes the overlay first).

const stack: { close: () => void }[] = [];

/** Registers an open overlay; the returned function takes it off again. */
export function openOverlay(close: () => void): () => void {
  const entry = { close };
  stack.push(entry);
  return () => {
    const index = stack.indexOf(entry);
    if (index !== -1) stack.splice(index, 1);
  };
}

/** Closes the newest open overlay; false when none is open. */
export function closeTopOverlay(): boolean {
  const top = stack.at(-1);
  if (top === undefined) return false;
  top.close();
  return true;
}

export function hasOverlay(): boolean {
  return stack.length > 0;
}
