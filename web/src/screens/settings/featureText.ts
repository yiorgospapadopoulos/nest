/** A piece of a feature's text: plain words, or a backtick span shown as code. */
export interface TextRun {
  code: boolean;
  text: string;
}

/** A feature's text split into runs; backticks with nothing between them stay as text. */
export function textRuns(text: string): TextRun[] {
  return text
    .split(/`([^`]+)`/)
    .map((part, index) => ({ code: index % 2 === 1, text: part }))
    .filter((run) => run.text !== "");
}
