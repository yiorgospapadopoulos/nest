/**
 * The draft with what was said put in at `at`, a space either side where the words would
 * otherwise touch, and where the caret goes: after the words.
 */
export function withSpoken(
  text: string,
  at: number,
  spoken: string,
): { text: string; caret: number } {
  const words = spoken.trim();
  const place = Math.max(0, Math.min(at, text.length));
  if (words === "") return { text, caret: place };
  const before = text.slice(0, place);
  const after = text.slice(place);
  const lead = before === "" || /\s$/.test(before) ? "" : " ";
  const tail = after === "" || /^\s/.test(after) ? "" : " ";
  const inserted = lead + words + tail;
  return { text: before + inserted + after, caret: place + lead.length + words.length };
}
