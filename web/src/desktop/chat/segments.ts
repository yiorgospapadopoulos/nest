// The shell commands in assistant messages, ported from NestKit's ShellCommand.swift:
// fenced blocks marked as shell, or an unmarked block of one line that starts with a
// common command, get their own block with Copy.

export type MessageSegment = { kind: "markdown"; text: string } | { kind: "command"; text: string };

const LANGUAGES = new Set(["sh", "bash", "zsh", "shell"]);

const COMMON = new Set(
  (
    "brew bun cargo cat cd chmod claude cp curl deno docker echo export find gh git go grep " +
    "kill launchctl ls lsof make mkdir mv node npm npx open pip pip3 pnpm ps pytest python " +
    "python3 rm ruff rsync scp sed source ssh sudo swift tail tailscale tar touch uv uvx " +
    "which xcodebuild xcrun yarn"
  ).split(" "),
);

/** The command a code block holds, without "$ " prompts; null when it is not one. */
export function blockCommand(language: string | null, code: string): string | null {
  const lines = code
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
  if (lines.length === 0) return null;
  const prompted = lines.every((line) => line.startsWith("$ "));
  const commands = prompted ? lines.map((line) => line.slice(2)) : lines;
  if (language !== null && LANGUAGES.has(language.toLowerCase())) return commands.join("\n");
  const first = commands[0];
  if (language !== null || commands.length !== 1 || first === undefined) return null;
  const word = /^\S*/.exec(first)?.[0] ?? "";
  return COMMON.has(word) || word.startsWith("./") ? first : null;
}

/** The message split around its shell command blocks; a block still streaming stays text. */
export function segments(markdown: string): MessageSegment[] {
  const out: MessageSegment[] = [];
  let pending: string[] = [];
  let block: { language: string | null; lines: string[] } | null = null;
  const flush = () => {
    const text = pending.join("\n");
    if (text.trim() !== "") out.push({ kind: "markdown", text });
    pending = [];
  };
  for (const line of markdown.split("\n")) {
    const fence = line.trim().startsWith("```");
    if (block === null) {
      if (fence) {
        const info = line.trim().slice(3).trim();
        block = { language: info === "" ? null : info, lines: [line] };
      } else pending.push(line);
      continue;
    }
    if (!fence) {
      block.lines.push(line);
      continue;
    }
    const command = blockCommand(block.language, block.lines.slice(1).join("\n"));
    if (command === null) pending.push(...block.lines, line);
    else {
      flush();
      out.push({ kind: "command", text: command });
    }
    block = null;
  }
  if (block !== null) pending.push(...block.lines);
  flush();
  return out;
}
