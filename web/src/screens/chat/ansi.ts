/** A run of terminal output in one style: an SGR colour code (30-37, 90-97) and bold. */
export interface AnsiSpan {
  text: string;
  color: number | null;
  bold: boolean;
}

// An escape sequence: a CSI (its parameters and final byte; the final byte is missing when
// the output stops in the middle of one), an OSC up to its terminator, or a short one such as ESC 7.
// eslint-disable-next-line no-control-regex
const ESCAPE = /\x1b(?:\[([0-9;?<=>]*)([@-~])?|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[ -/]*[0-~])?/g;
// Control characters other than newline and tab.
// eslint-disable-next-line no-control-regex
const CONTROL = /[\x00-\x08\x0b-\x1f\x7f]/g;

interface Style {
  color: number | null;
  bold: boolean;
}

/**
 * A run's raw output as styled spans (B108): the basic SGR colours and bold are kept,
 * every other escape is dropped. A carriage return starts its line again, as a progress
 * line that redraws itself shows only its latest state.
 */
export function ansiSpans(raw: string): AnsiSpan[] {
  const text = raw
    .split("\n")
    .map((line) => line.replace(/\r+$/, "").replace(/^.*\r/s, ""))
    .join("\n");
  const spans: AnsiSpan[] = [];
  let style: Style = { color: null, bold: false };
  let from = 0;
  const add = (part: string) => {
    const clean = part.replace(CONTROL, "");
    if (clean === "") return;
    const last = spans.at(-1);
    if (last?.color === style.color && last.bold === style.bold) last.text += clean;
    else spans.push({ text: clean, ...style });
  };
  for (const match of text.matchAll(ESCAPE)) {
    add(text.slice(from, match.index));
    from = match.index + match[0].length;
    if (match[2] === "m") style = sgr(style, String(match[1]));
  }
  add(text.slice(from));
  return spans;
}

/** The style after one SGR sequence's parameters. */
function sgr(from: Style, params: string): Style {
  const style = { ...from };
  // A 256 or true colour (38 or 48, then 5;n or 2;r;g;b) is skipped whole.
  let extended = false;
  let skip = 0;
  for (const code of params.split(";").map(Number)) {
    if (extended) {
      extended = false;
      skip = code === 5 ? 1 : 3;
    } else if (skip > 0) skip -= 1;
    else if (code === 0) {
      style.color = null;
      style.bold = false;
    } else if (code === 1) style.bold = true;
    else if (code === 22) style.bold = false;
    else if (code === 39) style.color = null;
    else if ((code >= 30 && code <= 37) || (code >= 90 && code <= 97)) style.color = code;
    else if (code === 38 || code === 48) extended = true;
  }
  return style;
}
