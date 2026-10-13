// Fact lines of a pixie's MEMORY.md (D057).

// A fact line of MEMORY.md, as the pixie writes them: "- YYYY-MM-DD: <fact>".
const DATED = /^- \d{4}-\d{2}-\d{2}: /;

export const isFact = (line: string) => line.startsWith("- ");

/** The fact lines of MEMORY.md. */
export function factLines(text: string): string[] {
  return text.split("\n").filter(isFact);
}

/** A fact's date (empty for a line written without one) and text. */
export function factParts(line: string) {
  return DATED.test(line)
    ? { date: line.slice(2, 12), text: line.slice(14) }
    : { date: "", text: line.slice(2) };
}

/** Today in the user's time zone, as a fact line's date. */
export function today(): string {
  const now = new Date();
  const two = (n: number) => String(n).padStart(2, "0");
  return `${String(now.getFullYear())}-${two(now.getMonth() + 1)}-${two(now.getDate())}`;
}
