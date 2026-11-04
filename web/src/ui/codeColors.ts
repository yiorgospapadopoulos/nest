// The small colouring of code blocks (B118): no library, so languages outside this list stay
// plain. A scan by hand that only ever moves forward, so its time follows the code's length.
// `apple/Sources/NestKit/Presentation/CodeColors.swift` is its twin, with the same token
// kinds and offsets in UTF-16 units; design/code-colors-sample.json holds both to that.

export type CodeKind = "comment" | "string" | "keyword" | "number" | "added" | "removed";

export interface CodeToken {
  kind: CodeKind;
  start: number;
  end: number;
}

/** Longer code stays plain, so a huge block costs nothing. */
export const MAX_COLOURED = 32_000;

interface Quote {
  mark: string;
  // Runs on over line breaks; any other string ends with its line when it is left open.
  multiline?: boolean;
  // A backslash means nothing in it.
  raw?: boolean;
}

interface Language {
  lineComments: string[];
  blockComments: [string, string][];
  quotes: Quote[];
  keywords: Set<string>;
  // Keywords in any case.
  folded?: boolean;
  // More characters a word can start with, and hold.
  wordStart?: string;
  wordPart?: string;
  // `#` opens a comment only at the start of a word, as `$#` and `a#b` show it does not.
  spacedHash?: boolean;
  // `'` opens a string only away from a word: `don't` is not one.
  boundQuote?: boolean;
  // `'` opens only a one character literal: Rust's lifetimes are not strings.
  charQuote?: boolean;
  // A number is a whole word of digits: `v1.2` and `file2` are not numbers.
  shell?: boolean;
}

const words = (text: string) => new Set(text.split(" "));

const C_COMMENTS: Pick<Language, "lineComments" | "blockComments"> = {
  lineComments: ["//"],
  blockComments: [["/*", "*/"]],
};
const PLAIN_QUOTES: Quote[] = [{ mark: '"' }, { mark: "'" }];
const SCRIPT_QUOTES: Quote[] = [...PLAIN_QUOTES, { mark: "`", multiline: true }];

const JS_WORDS =
  "as async await break case catch class const continue debugger default delete do else export extends false finally for from function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while with yield";
const TS_WORDS = `${JS_WORDS} abstract declare enum implements interface keyof namespace private protected public readonly satisfies type`;

const JS: Language = {
  ...C_COMMENTS,
  quotes: SCRIPT_QUOTES,
  keywords: words(JS_WORDS),
  boundQuote: true,
};
const TS: Language = { ...JS, keywords: words(TS_WORDS) };
const SHELL: Language = {
  lineComments: ["#"],
  blockComments: [],
  quotes: [{ mark: '"' }, { mark: "'", raw: true }],
  keywords: words(
    "alias case declare do done elif else esac exit export fi for function if in local readonly return select source then unset until while",
  ),
  wordStart: "-./~",
  wordPart: "-./:=@%+~",
  spacedHash: true,
  boundQuote: true,
  shell: true,
};
const JSON_LANGUAGE: Language = {
  ...C_COMMENTS,
  quotes: [{ mark: '"' }],
  keywords: words("false null true"),
};

const LANGUAGES: Record<string, Language> = {
  swift: {
    ...C_COMMENTS,
    quotes: [{ mark: '"""', multiline: true }, { mark: '"' }],
    keywords: words(
      "actor any as associatedtype async await break case catch class continue default defer deinit do else enum extension fallthrough false fileprivate final for func guard if import in init inout internal is let mutating nil nonisolated open override private protocol public repeat rethrows return self Self some static struct subscript super switch throw throws true try typealias var weak where while",
    ),
  },
  js: JS,
  ts: TS,
  python: {
    lineComments: ["#"],
    blockComments: [],
    quotes: [{ mark: '"""', multiline: true }, { mark: "'''", multiline: true }, ...PLAIN_QUOTES],
    keywords: words(
      "False None True and as assert async await break case class continue def del elif else except finally for from global if import in is lambda match nonlocal not or pass raise return self try while with yield",
    ),
  },
  rust: {
    ...C_COMMENTS,
    quotes: PLAIN_QUOTES,
    keywords: words(
      "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
    ),
    charQuote: true,
  },
  go: {
    ...C_COMMENTS,
    quotes: [...PLAIN_QUOTES, { mark: "`", multiline: true, raw: true }],
    keywords: words(
      "break case chan const continue default defer else fallthrough false for func go goto if import interface iota map nil package range return select struct switch true type var",
    ),
    boundQuote: true,
  },
  bash: SHELL,
  json: JSON_LANGUAGE,
  toml: {
    lineComments: ["#"],
    blockComments: [],
    quotes: [
      { mark: '"""', multiline: true },
      { mark: "'''", multiline: true, raw: true },
      { mark: '"' },
      { mark: "'", raw: true },
    ],
    keywords: words("false true"),
    wordPart: "-",
    boundQuote: true,
  },
  yaml: {
    lineComments: ["#"],
    blockComments: [],
    quotes: [{ mark: '"' }, { mark: "'", raw: true }],
    keywords: words("false no null off on true yes"),
    wordPart: "-",
    spacedHash: true,
    boundQuote: true,
  },
  css: {
    lineComments: [],
    blockComments: [["/*", "*/"]],
    quotes: PLAIN_QUOTES,
    keywords: words(
      "@charset @container @font-face @import @keyframes @layer @media @supports auto important inherit initial none unset",
    ),
    wordStart: "@",
    wordPart: "-",
    boundQuote: true,
  },
  sql: {
    lineComments: ["--"],
    blockComments: [["/*", "*/"]],
    quotes: [
      { mark: "'", raw: true },
      { mark: '"', raw: true },
    ],
    keywords: words(
      "add all alter and as asc begin between by case check commit constraint create default delete desc distinct drop else end exists false foreign from group having if in index inner insert into is join key left like limit not null offset on or order outer primary references returning right rollback select set table then transaction true union unique update using values view when where with",
    ),
    folded: true,
  },
};

const ALIASES: Record<string, string> = {
  swift: "swift",
  ts: "ts",
  tsx: "ts",
  typescript: "ts",
  mts: "ts",
  cts: "ts",
  js: "js",
  jsx: "js",
  javascript: "js",
  mjs: "js",
  cjs: "js",
  node: "js",
  python: "python",
  python3: "python",
  py: "python",
  py3: "python",
  rust: "rust",
  rs: "rust",
  go: "go",
  golang: "go",
  bash: "bash",
  sh: "bash",
  zsh: "bash",
  shell: "bash",
  shellscript: "bash",
  json: "json",
  jsonc: "json",
  json5: "json",
  toml: "toml",
  yaml: "yaml",
  yml: "yaml",
  html: "html",
  htm: "html",
  css: "css",
  sql: "sql",
  postgresql: "sql",
  mysql: "sql",
  sqlite: "sql",
  diff: "diff",
  patch: "diff",
};

const unit = (char: string) => char.charCodeAt(0);
const LINE = unit("\n");
const BACKSLASH = unit("\\");
const QUOTE = unit("'");

const isDigit = (c: number) => c >= 48 && c <= 57;
const isLetter = (c: number) => (c >= 65 && c <= 90) || (c >= 97 && c <= 122);
const isAlnum = (c: number) => isLetter(c) || isDigit(c);
const isSpace = (c: number) => c === 32 || c === 9 || c === LINE || c === 13;
// Past the end `charCodeAt` reads NaN, which fails every test here.
const isWord = (c: number) => isAlnum(c) || c === 95 || c === 36 || c >= 128;

function indexOr(code: string, mark: string, from: number): number {
  const found = code.indexOf(mark, from);
  return found === -1 ? code.length : found;
}

/** Where the string opened at `at` ends: past its close, else at its line's end or the code's. */
function stringEnd(code: string, at: number, quote: Quote): number {
  let index = at + quote.mark.length;
  while (index < code.length) {
    const c = code.charCodeAt(index);
    if (c === BACKSLASH && quote.raw !== true) {
      index += 2;
    } else if (code.startsWith(quote.mark, index)) {
      return index + quote.mark.length;
    } else if (c === LINE && quote.multiline !== true) {
      return index;
    } else {
      index += 1;
    }
  }
  return code.length;
}

/** Where the number at `at` ends, and whether it is one: `1.2.3` is a version, left plain. */
function numberEnd(code: string, at: number): { end: number; isNumber: boolean } {
  const digits = (from: number) => {
    let index = from;
    while (isDigit(code.charCodeAt(index)) || code.charCodeAt(index) === 95) index += 1;
    return index;
  };
  const suffix = (from: number) => {
    let index = from;
    while (isAlnum(code.charCodeAt(index)) || code.charCodeAt(index) === 95) index += 1;
    return index;
  };
  const second = code.charAt(at + 1).toLowerCase();
  if (code.charAt(at) === "0" && (second === "x" || second === "b" || second === "o")) {
    return { end: suffix(at + 2), isNumber: true };
  }
  let end = digits(at);
  if (code.charAt(end) === "." && isDigit(code.charCodeAt(end + 1))) {
    end = digits(end + 1);
    if (code.charAt(end) === "." && isDigit(code.charCodeAt(end + 1))) {
      while (code.charAt(end) === "." || isDigit(code.charCodeAt(end))) end += 1;
      return { end, isNumber: false };
    }
  }
  if (code.charAt(end).toLowerCase() === "e") {
    const sign = code.charAt(end + 1) === "+" || code.charAt(end + 1) === "-" ? 1 : 0;
    if (isDigit(code.charCodeAt(end + 1 + sign))) end = digits(end + 1 + sign);
  }
  return { end: suffix(end), isNumber: true };
}

function scanCode(language: Language, code: string): CodeToken[] {
  const tokens: CodeToken[] = [];
  const isWordStart = (c: number) =>
    isWord(c) || (language.wordStart?.includes(String.fromCharCode(c)) ?? false);
  const isWordPart = (c: number) =>
    isWord(c) || (language.wordPart?.includes(String.fromCharCode(c)) ?? false);

  const commentEnd = (at: number): number | null => {
    for (const mark of language.lineComments) {
      if (!code.startsWith(mark, at)) continue;
      if (language.spacedHash === true && at > 0 && !isSpace(code.charCodeAt(at - 1))) continue;
      return indexOr(code, "\n", at);
    }
    for (const [open, close] of language.blockComments) {
      if (!code.startsWith(open, at)) continue;
      const end = indexOr(code, close, at + open.length);
      return Math.min(end + close.length, code.length);
    }
    return null;
  };

  const quoteAt = (at: number): Quote | null => {
    for (const quote of language.quotes) {
      if (!code.startsWith(quote.mark, at)) continue;
      if (code.charCodeAt(at) === QUOTE) {
        if (language.boundQuote === true && isAlnum(code.charCodeAt(at - 1))) return null;
        if (
          language.charQuote === true &&
          code.charCodeAt(at + 1) !== BACKSLASH &&
          code.charCodeAt(at + 2) !== QUOTE
        ) {
          return null;
        }
      }
      return quote;
    }
    return null;
  };

  let at = 0;
  while (at < code.length) {
    const c = code.charCodeAt(at);
    const comment = commentEnd(at);
    if (comment !== null) {
      tokens.push({ kind: "comment", start: at, end: comment });
      at = comment;
      continue;
    }
    const quote = quoteAt(at);
    if (quote !== null) {
      const end = stringEnd(code, at, quote);
      tokens.push({ kind: "string", start: at, end });
      at = end;
      continue;
    }
    if (!isWordStart(c)) {
      at += 1;
      continue;
    }
    let end = at + 1;
    while (isWordPart(code.charCodeAt(end))) end += 1;
    if (isDigit(c) && language.shell !== true) {
      const number = numberEnd(code, at);
      if (number.isNumber) tokens.push({ kind: "number", start: at, end: number.end });
      at = number.end;
      continue;
    }
    if (isDigit(c)) {
      let digits = at;
      while (isDigit(code.charCodeAt(digits))) digits += 1;
      if (digits === end) tokens.push({ kind: "number", start: at, end });
    } else {
      const word = code.slice(at, end);
      const known = language.keywords.has(language.folded === true ? word.toLowerCase() : word);
      if (known && code.charAt(at - 1) !== ".") tokens.push({ kind: "keyword", start: at, end });
    }
    at = end;
  }
  return tokens;
}

/** Tags by name and their attributes' strings; what stands between tags stays plain. */
function scanHtml(code: string): CodeToken[] {
  const tokens: CodeToken[] = [];
  const quote: Quote = { mark: '"', multiline: true, raw: true };
  let at = 0;
  while (at < code.length) {
    const open = indexOr(code, "<", at);
    if (open === code.length) break;
    if (code.startsWith("<!--", open)) {
      const end = Math.min(indexOr(code, "-->", open + 4) + 3, code.length);
      tokens.push({ kind: "comment", start: open, end });
      at = end;
      continue;
    }
    const name = code.charAt(open + 1) === "/" ? open + 2 : open + 1;
    if (!isLetter(code.charCodeAt(name))) {
      at = open + 1;
      continue;
    }
    let index = name;
    while (isAlnum(code.charCodeAt(index)) || code.charAt(index) === "-") index += 1;
    tokens.push({ kind: "keyword", start: name, end: index });
    while (index < code.length && code.charAt(index) !== ">") {
      const char = code.charAt(index);
      if (char === '"' || char === "'") {
        const end = stringEnd(code, index, { ...quote, mark: char });
        tokens.push({ kind: "string", start: index, end });
        index = end;
      } else {
        index += 1;
      }
    }
    at = index + 1;
  }
  return tokens;
}

/** Added and removed lines, and the file and hunk lines as quiet as comments. */
function scanDiff(code: string): CodeToken[] {
  const tokens: CodeToken[] = [];
  let at = 0;
  while (at < code.length) {
    const end = indexOr(code, "\n", at);
    let kind: CodeKind | null = null;
    if (code.startsWith("+++", at) || code.startsWith("---", at) || code.startsWith("@@", at)) {
      kind = "comment";
    } else if (code.charAt(at) === "+") {
      kind = "added";
    } else if (code.charAt(at) === "-") {
      kind = "removed";
    }
    if (kind !== null) tokens.push({ kind, start: at, end });
    at = end + 1;
  }
  return tokens;
}

/** The language a fence names: its first word, in lower case; null with none. */
function languageName(info: string | null): string | null {
  const first = info?.trim().split(/\s+/)[0]?.toLowerCase();
  if (first === undefined || first === "") return null;
  return Object.hasOwn(ALIASES, first) ? (ALIASES[first] ?? null) : null;
}

/** The coloured stretches of a code block, in order; none for a language not known here. */
export function codeTokens(info: string | null, code: string): CodeToken[] {
  const name = languageName(info);
  if (name === null || code.length > MAX_COLOURED) return [];
  if (name === "html") return scanHtml(code);
  if (name === "diff") return scanDiff(code);
  const language = LANGUAGES[name];
  return language === undefined ? [] : scanCode(language, code);
}
