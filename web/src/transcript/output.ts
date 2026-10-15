/**
 * How much of a tool's output a row shows before it is opened further, like Claude's
 * apps: the first few lines, never more than a screenful of characters (B59). The whole
 * output stays in the transcript; only the preview renders until asked for.
 */

export const PREVIEW_LINES = 8;
export const PREVIEW_CHARS = 1200;

export interface OutputPreview {
  text: string;
  // All the output's lines.
  lines: number;
  // Whether there is more than the preview.
  cut: boolean;
}

export function outputPreview(output: string): OutputPreview {
  const text = output.trimEnd();
  let lines = 1;
  let end = text.length;
  for (let at = text.indexOf("\n"); at !== -1; at = text.indexOf("\n", at + 1)) {
    if (lines === PREVIEW_LINES) end = at;
    lines += 1;
  }
  end = Math.min(end, PREVIEW_CHARS);
  return { text: text.slice(0, end), lines, cut: end < text.length };
}
