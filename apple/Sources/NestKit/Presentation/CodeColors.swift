import Foundation

/// A coloured stretch of a code block, in UTF-16 offsets into it.
public struct CodeToken: Sendable, Hashable {
    public enum Kind: String, Sendable, Hashable {
        case comment, string, keyword, number, added, removed
    }

    public let kind: Kind
    public let start: Int
    public let end: Int

    public init(kind: Kind, start: Int, end: Int) {
        self.kind = kind
        self.start = start
        self.end = end
    }
}

/// The small colouring of code blocks (B118): no library, so languages outside this list stay
/// plain. A scan by hand that only ever moves forward, so its time follows the code's length.
/// `web/src/ui/codeColors.ts` is its twin, with the same token kinds and offsets;
/// design/code-colors-sample.json holds both to that.
public enum CodeColors {
    /// Longer code stays plain, so a huge block costs nothing.
    public static let maxLength = 32_000

    /// The coloured stretches of a code block, in order; none for a language not known here.
    public static func tokens(language info: String?, code: String) -> [CodeToken] {
        guard let name = languageName(info), code.utf16.count <= maxLength else { return [] }
        let units = Array(code.utf16)
        switch name {
        case "html": return scanHTML(units)
        case "diff": return scanDiff(units)
        default:
            guard let language = languages[name] else { return [] }
            return CodeScanner(language: language, units: units).tokens()
        }
    }

    /// The language a fence names: its first word, in lower case; nil with none.
    private static func languageName(_ info: String?) -> String? {
        guard let first = info?.split(whereSeparator: \.isWhitespace).first else { return nil }
        return aliases[first.lowercased()]
    }

    /// Tags by name and their attributes' strings; what stands between tags stays plain.
    private static func scanHTML(_ units: [UInt16]) -> [CodeToken] {
        var tokens: [CodeToken] = []
        let marks = Marks(units)
        var at = 0
        while at < units.count {
            let open = marks.index(of: Mark.tagOpen, from: at)
            if open == units.count {
                break
            }
            if marks.starts(Mark.htmlCommentOpen, at: open) {
                let close = marks.index(of: Mark.htmlCommentClose, from: open + 4)
                let end = min(close + 3, units.count)
                tokens.append(CodeToken(kind: .comment, start: open, end: end))
                at = end
                continue
            }
            let name = marks.unit(open + 1) == Unit.slash ? open + 2 : open + 1
            guard Unit.isLetter(marks.unit(name)) else {
                at = open + 1
                continue
            }
            var index = name
            while Unit.isAlnum(marks.unit(index))
                || marks.unit(index) == Unit.dash
            {
                index += 1
            }
            tokens.append(CodeToken(kind: .keyword, start: name, end: index))
            while index < units.count, units[index] != Unit.tagClose {
                let unit = units[index]
                if unit == Unit.doubleQuote || unit == Unit.singleQuote {
                    let quote = Quote(mark: [unit], multiline: true, raw: true)
                    let end = marks.stringEnd(at: index, quote)
                    tokens.append(CodeToken(kind: .string, start: index, end: end))
                    index = end
                } else {
                    index += 1
                }
            }
            at = index + 1
        }
        return tokens
    }

    /// Added and removed lines, and the file and hunk lines as quiet as comments.
    private static func scanDiff(_ units: [UInt16]) -> [CodeToken] {
        var tokens: [CodeToken] = []
        let marks = Marks(units)
        var at = 0
        while at < units.count {
            let end = marks.index(of: Mark.line, from: at)
            var kind: CodeToken.Kind?
            if marks.starts(Mark.added, at: at) || marks.starts(Mark.removed, at: at)
                || marks.starts(Mark.hunk, at: at)
            {
                kind = .comment
            } else if units[at] == Unit.plus {
                kind = .added
            } else if units[at] == Unit.dash {
                kind = .removed
            }
            if let kind {
                tokens.append(CodeToken(kind: kind, start: at, end: end))
            }
            at = end + 1
        }
        return tokens
    }

    // MARK: Languages

    private static func words(_ text: String) -> Set<String> {
        Set(text.split(separator: " ").map(String.init))
    }

    private static let cLine = [Mark.make("//")]
    private static let cBlock = [(Mark.make("/*"), Mark.make("*/"))]
    private static let double = Quote(mark: Mark.make("\""))
    private static let single = Quote(mark: Mark.make("'"))
    private static let singleRaw = Quote(mark: Mark.make("'"), raw: true)
    private static let tripleDouble = Quote(mark: Mark.make("\"\"\""), multiline: true)
    private static let tripleSingle = Quote(mark: Mark.make("'''"), multiline: true)
    private static let backtick = Quote(mark: Mark.make("`"), multiline: true)

    private static let jsWords = """
        as async await break case catch class const continue debugger default delete do else \
        export extends false finally for from function if import in instanceof let new null of \
        return static super switch this throw true try typeof undefined var void while with \
        yield
        """
    private static let tsWords = """
        abstract declare enum implements interface keyof namespace private protected public \
        readonly satisfies type
        """

    private static let js = CodeLanguage(
        lineComments: cLine, blockComments: cBlock, quotes: [double, single, backtick],
        keywords: words(jsWords), boundQuote: true)

    private static let languages: [String: CodeLanguage] = [
        "swift": CodeLanguage(
            lineComments: cLine, blockComments: cBlock, quotes: [tripleDouble, double],
            keywords: words(
                """
                actor any as associatedtype async await break case catch class continue default \
                defer deinit do else enum extension fallthrough false fileprivate final for func \
                guard if import in init inout internal is let mutating nil nonisolated open \
                override private protocol public repeat rethrows return self Self some static \
                struct subscript super switch throw throws true try typealias var weak where while
                """
            )),
        "js": js,
        "ts": CodeLanguage(
            lineComments: cLine, blockComments: cBlock, quotes: [double, single, backtick],
            keywords: words(jsWords + " " + tsWords), boundQuote: true),
        "python": CodeLanguage(
            lineComments: [Mark.make("#")], blockComments: [],
            quotes: [tripleDouble, tripleSingle, double, single],
            keywords: words(
                """
                False None True and as assert async await break case class continue def del elif \
                else except finally for from global if import in is lambda match nonlocal not or \
                pass raise return self try while with yield
                """
            )),
        "rust": CodeLanguage(
            lineComments: cLine, blockComments: cBlock, quotes: [double, single],
            keywords: words(
                """
                as async await break const continue crate dyn else enum extern false fn for if \
                impl in let loop match mod move mut pub ref return self Self static struct super \
                trait true type unsafe use where while
                """
            ), charQuote: true),
        "go": CodeLanguage(
            lineComments: cLine, blockComments: cBlock,
            quotes: [double, single, Quote(mark: Mark.make("`"), multiline: true, raw: true)],
            keywords: words(
                """
                break case chan const continue default defer else fallthrough false for func go \
                goto if import interface iota map nil package range return select struct switch \
                true type var
                """
            ), boundQuote: true),
        "bash": CodeLanguage(
            lineComments: [Mark.make("#")], blockComments: [], quotes: [double, singleRaw],
            keywords: words(
                """
                alias case declare do done elif else esac exit export fi for function if in local \
                readonly return select source then unset until while
                """
            ), wordStart: Mark.make("-./~"), wordPart: Mark.make("-./:=@%+~"), spacedHash: true,
            boundQuote: true, shell: true),
        "json": CodeLanguage(
            lineComments: cLine, blockComments: cBlock, quotes: [double],
            keywords: words("false null true")),
        "toml": CodeLanguage(
            lineComments: [Mark.make("#")], blockComments: [],
            quotes: [
                tripleDouble, Quote(mark: Mark.make("'''"), multiline: true, raw: true), double,
                singleRaw,
            ],
            keywords: words("false true"), wordPart: Mark.make("-"), boundQuote: true),
        "yaml": CodeLanguage(
            lineComments: [Mark.make("#")], blockComments: [], quotes: [double, singleRaw],
            keywords: words("false no null off on true yes"), wordPart: Mark.make("-"),
            spacedHash: true, boundQuote: true),
        "css": CodeLanguage(
            lineComments: [], blockComments: cBlock, quotes: [double, single],
            keywords: words(
                """
                @charset @container @font-face @import @keyframes @layer @media @supports auto \
                important inherit initial none unset
                """
            ), wordStart: Mark.make("@"), wordPart: Mark.make("-"), boundQuote: true),
        "sql": CodeLanguage(
            lineComments: [Mark.make("--")], blockComments: cBlock,
            quotes: [singleRaw, Quote(mark: Mark.make("\""), raw: true)],
            keywords: words(
                """
                add all alter and as asc begin between by case check commit constraint create \
                default delete desc distinct drop else end exists false foreign from group having \
                if in index inner insert into is join key left like limit not null offset on or \
                order outer primary references returning right rollback select set table then \
                transaction true union unique update using values view when where with
                """
            ), folded: true),
    ]

    private static let aliases: [String: String] = [
        "swift": "swift",
        "ts": "ts",
        "tsx": "ts",
        "typescript": "ts",
        "mts": "ts",
        "cts": "ts",
        "js": "js",
        "jsx": "js",
        "javascript": "js",
        "mjs": "js",
        "cjs": "js",
        "node": "js",
        "python": "python",
        "python3": "python",
        "py": "python",
        "py3": "python",
        "rust": "rust",
        "rs": "rust",
        "go": "go",
        "golang": "go",
        "bash": "bash",
        "sh": "bash",
        "zsh": "bash",
        "shell": "bash",
        "shellscript": "bash",
        "json": "json",
        "jsonc": "json",
        "json5": "json",
        "toml": "toml",
        "yaml": "yaml",
        "yml": "yaml",
        "html": "html",
        "htm": "html",
        "css": "css",
        "sql": "sql",
        "postgresql": "sql",
        "mysql": "sql",
        "sqlite": "sql",
        "diff": "diff",
        "patch": "diff",
    ]
}

private enum Mark {
    static func make(_ text: String) -> [UInt16] { Array(text.utf16) }

    static let line = make("\n")
    static let tagOpen = make("<")
    static let htmlCommentOpen = make("<!--")
    static let htmlCommentClose = make("-->")
    static let added = make("+++")
    static let removed = make("---")
    static let hunk = make("@@")
}

private enum Unit {
    static let line: UInt16 = 10
    static let carriageReturn: UInt16 = 13
    static let space: UInt16 = 32
    static let tab: UInt16 = 9
    static let doubleQuote: UInt16 = 34
    static let dollar: UInt16 = 36
    static let singleQuote: UInt16 = 39
    static let plus: UInt16 = 43
    static let dash: UInt16 = 45
    static let dot: UInt16 = 46
    static let slash: UInt16 = 47
    static let tagClose: UInt16 = 62
    static let backslash: UInt16 = 92
    static let underscore: UInt16 = 95

    static func isDigit(_ unit: UInt16?) -> Bool {
        guard let unit else { return false }
        return unit >= 48 && unit <= 57
    }

    static func isLetter(_ unit: UInt16?) -> Bool {
        guard let unit else { return false }
        return (unit >= 65 && unit <= 90) || (unit >= 97 && unit <= 122)
    }

    static func isAlnum(_ unit: UInt16?) -> Bool {
        isLetter(unit) || isDigit(unit)
    }

    static func isSpace(_ unit: UInt16?) -> Bool {
        unit == space || unit == tab || unit == line || unit == carriageReturn
    }

    static func isWord(_ unit: UInt16?) -> Bool {
        guard let unit else { return false }
        return isAlnum(unit) || unit == underscore || unit == dollar || unit >= 128
    }
}

private struct Quote {
    let mark: [UInt16]
    /// Runs on over line breaks; any other string ends with its line when it is left open.
    var multiline = false
    /// A backslash means nothing in it.
    var raw = false
}

private struct CodeLanguage {
    let lineComments: [[UInt16]]
    let blockComments: [([UInt16], [UInt16])]
    let quotes: [Quote]
    let keywords: Set<String>
    /// Keywords in any case.
    var folded = false
    /// More characters a word can start with, and hold.
    var wordStart: [UInt16] = []
    var wordPart: [UInt16] = []
    /// `#` opens a comment only at the start of a word, as `$#` and `a#b` show it does not.
    var spacedHash = false
    /// `'` opens a string only away from a word: `don't` is not one.
    var boundQuote = false
    /// `'` opens only a one character literal: Rust's lifetimes are not strings.
    var charQuote = false
    /// A number is a whole word of digits: `v1.2` and `file2` are not numbers.
    var shell = false
}

/// The code's units with the searches every scan uses.
private struct Marks {
    let units: [UInt16]

    init(_ units: [UInt16]) {
        self.units = units
    }

    func unit(_ index: Int) -> UInt16? {
        index >= 0 && index < units.count ? units[index] : nil
    }

    func starts(_ mark: [UInt16], at index: Int) -> Bool {
        guard index + mark.count <= units.count else { return false }
        for offset in mark.indices where units[index + offset] != mark[offset] {
            return false
        }
        return true
    }

    /// Where `mark` next stands from `start`, else the end of the code.
    func index(of mark: [UInt16], from start: Int) -> Int {
        var index = start
        while index + mark.count <= units.count {
            if starts(mark, at: index) {
                return index
            }
            index += 1
        }
        return units.count
    }

    /// Where the string opened at `at` ends: past its close, else at its line's end or the
    /// code's.
    func stringEnd(at: Int, _ quote: Quote) -> Int {
        var index = at + quote.mark.count
        while index < units.count {
            let unit = units[index]
            if unit == Unit.backslash, !quote.raw {
                index += 2
            } else if starts(quote.mark, at: index) {
                return index + quote.mark.count
            } else if unit == Unit.line, !quote.multiline {
                return index
            } else {
                index += 1
            }
        }
        return units.count
    }
}

private struct CodeScanner {
    let language: CodeLanguage
    let marks: Marks

    init(language: CodeLanguage, units: [UInt16]) {
        self.language = language
        marks = Marks(units)
    }

    private func isWordStart(_ unit: UInt16?) -> Bool {
        Unit.isWord(unit) || unit.map(language.wordStart.contains) == true
    }

    private func isWordPart(_ unit: UInt16?) -> Bool {
        Unit.isWord(unit) || unit.map(language.wordPart.contains) == true
    }

    private func commentEnd(at: Int) -> Int? {
        for mark in language.lineComments where marks.starts(mark, at: at) {
            if language.spacedHash, at > 0, !Unit.isSpace(marks.unit(at - 1)) {
                continue
            }
            return marks.index(of: Mark.line, from: at)
        }
        for (open, close) in language.blockComments where marks.starts(open, at: at) {
            let end = marks.index(of: close, from: at + open.count)
            return min(end + close.count, marks.units.count)
        }
        return nil
    }

    private func quote(at: Int) -> Quote? {
        for quote in language.quotes where marks.starts(quote.mark, at: at) {
            if marks.unit(at) == Unit.singleQuote {
                if language.boundQuote, Unit.isAlnum(marks.unit(at - 1)) {
                    return nil
                }
                if language.charQuote, marks.unit(at + 1) != Unit.backslash,
                    marks.unit(at + 2) != Unit.singleQuote
                {
                    return nil
                }
            }
            return quote
        }
        return nil
    }

    /// Where the number at `at` ends, and whether it is one: `1.2.3` is a version, left plain.
    private func number(at: Int) -> (end: Int, isNumber: Bool) {
        func digits(from start: Int) -> Int {
            var index = start
            while Unit.isDigit(marks.unit(index)) || marks.unit(index) == Unit.underscore {
                index += 1
            }
            return index
        }
        func suffix(from start: Int) -> Int {
            var index = start
            while Unit.isAlnum(marks.unit(index)) || marks.unit(index) == Unit.underscore {
                index += 1
            }
            return index
        }
        let base = marks.unit(at + 1).map { Int($0) | 32 }
        if marks.unit(at) == 48, base == 120 || base == 98 || base == 111 {
            return (suffix(from: at + 2), true)
        }
        var end = digits(from: at)
        if marks.unit(end) == Unit.dot, Unit.isDigit(marks.unit(end + 1)) {
            end = digits(from: end + 1)
            if marks.unit(end) == Unit.dot, Unit.isDigit(marks.unit(end + 1)) {
                while marks.unit(end) == Unit.dot || Unit.isDigit(marks.unit(end)) {
                    end += 1
                }
                return (end, false)
            }
        }
        if let unit = marks.unit(end), Int(unit) | 32 == 101 {
            let next = marks.unit(end + 1)
            let sign = next == Unit.plus || next == Unit.dash ? 1 : 0
            if Unit.isDigit(marks.unit(end + 1 + sign)) {
                end = digits(from: end + 1 + sign)
            }
        }
        return (suffix(from: end), true)
    }

    func tokens() -> [CodeToken] {
        var tokens: [CodeToken] = []
        let units = marks.units
        var at = 0
        while at < units.count {
            let unit = units[at]
            if let end = commentEnd(at: at) {
                tokens.append(CodeToken(kind: .comment, start: at, end: end))
                at = end
                continue
            }
            if let quote = quote(at: at) {
                let end = marks.stringEnd(at: at, quote)
                tokens.append(CodeToken(kind: .string, start: at, end: end))
                at = end
                continue
            }
            guard isWordStart(unit) else {
                at += 1
                continue
            }
            var end = at + 1
            while isWordPart(marks.unit(end)) {
                end += 1
            }
            if Unit.isDigit(unit), !language.shell {
                let number = number(at: at)
                if number.isNumber {
                    tokens.append(CodeToken(kind: .number, start: at, end: number.end))
                }
                at = number.end
                continue
            }
            if Unit.isDigit(unit) {
                var digits = at
                while Unit.isDigit(marks.unit(digits)) {
                    digits += 1
                }
                if digits == end {
                    tokens.append(CodeToken(kind: .number, start: at, end: end))
                }
            } else {
                let word = String(decoding: units[at..<end], as: UTF16.self)
                let known = language.keywords.contains(language.folded ? word.lowercased() : word)
                if known, marks.unit(at - 1) != Unit.dot {
                    tokens.append(CodeToken(kind: .keyword, start: at, end: end))
                }
            }
            at = end
        }
        return tokens
    }
}
