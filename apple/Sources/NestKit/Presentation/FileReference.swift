import Foundation

/// What in a message names a file (B118): a markdown link with no scheme, and path-like text
/// with an extension and an optional `:line`. The web's twin is `web/src/ui/fileRefs.ts`. The
/// text is the agent's and untrusted, so finding one only says what looks like a file;
/// `resolve` decides, at the click, whether it may open.
public enum FileReference {
    /// A file named in plain text, in UTF-16 offsets into it.
    public struct Found: Sendable, Hashable {
        public let start: Int
        public let end: Int
        public let path: String
    }

    /// Without a slash a name needs one of these: `a.b` is usually not a file.
    private static let common: Set<String> = [
        "bash", "bat", "c", "cc", "cfg", "cjs", "conf", "cpp", "cs", "css", "csv", "cts", "dart",
        "env", "ex", "exs", "fish", "go", "gradle", "graphql", "h", "hpp", "hs", "htm", "html",
        "ini", "java", "js", "json", "jsonc", "jsx", "kt", "kts", "lock", "lua", "markdown", "md",
        "mdx", "mjs", "mm", "mts", "nix", "php", "plist", "proto", "ps1", "py", "pyi", "rb", "rs",
        "rst", "sass", "scala", "scss", "sh", "sql", "svelte", "swift", "tf", "toml", "ts", "tsv",
        "tsx", "txt", "vue", "xml", "yaml", "yml", "zsh",
    ]
    /// Projects named like files.
    private static let names: Set<String> = [
        "node.js", "next.js", "nuxt.js", "vue.js", "deno.js", "three.js",
    ]
    /// Marks of a pattern or a shell word, not of a path someone would open.
    private static let notInPath = Set(":*?<>|\"$\\{}")
    /// What cannot stand right before a path: the rest of a URL, a variable, a glob.
    private static let before = Set(":\\$%#&*~".utf16)
    private static let pathMarks = Set("_-./@+".utf16)

    // MARK: Finding

    /// The files plain text names, in order.
    public static func inText(_ text: String) -> [Found] {
        let units = Array(text.utf16)
        func unit(_ index: Int) -> UInt16? {
            index >= 0 && index < units.count ? units[index] : nil
        }
        var found: [Found] = []
        var at = 0
        while at < units.count {
            guard isPathUnit(units[at]) else {
                at += 1
                continue
            }
            var end = at
            while end < units.count, isPathUnit(units[end]) {
                end += 1
            }
            var stop = end
            while stop > at, units[stop - 1] == dot {
                stop -= 1
            }
            let path = String(decoding: units[at..<stop], as: UTF16.self)
            let lineStop = stop == end ? lineEnd(units, from: stop) : stop
            if !(unit(at - 1).map(before.contains) ?? false), unit(lineStop) != parenthesis,
                looksLikeFile(path)
            {
                found.append(Found(start: at, end: lineStop, path: path))
            }
            at = max(end, lineStop)
        }
        return found
    }

    /// The file a whole code span names, if it is one path with an optional line.
    public static func inCode(_ code: String) -> String? {
        let path = withoutLine(code.trimmingCharacters(in: .whitespacesAndNewlines))
        guard !path.contains(where: { $0.isWhitespace || notInPath.contains($0) }) else {
            return nil
        }
        return looksLikeFile(path) ? path : nil
    }

    /// The file a markdown link with no scheme points at.
    public static func inLink(_ url: String) -> String? {
        let target = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !target.isEmpty, !target.hasPrefix("#"), !target.hasPrefix("//") else { return nil }
        let unanchored = target.firstIndex(of: "#").map { String(target[..<$0]) } ?? target
        let bare = withoutLine(unanchored)
        guard !hasScheme(bare), let path = bare.removingPercentEncoding else { return nil }
        guard !path.utf16.contains(where: { $0 < 32 }), !path.contains("\\"),
            !path.hasSuffix("/")
        else {
            return nil
        }
        let name = nameOf(path)
        guard name != ".", name != "..", !startsWithHost(path) else { return nil }
        if !path.contains("/"), name.contains("."), !common.contains(extensionOf(name) ?? "") {
            return nil
        }
        return path
    }

    private static let dot: UInt16 = 46
    private static let colon: UInt16 = 58
    private static let dash: UInt16 = 45
    private static let parenthesis: UInt16 = 40

    private static func isDigit(_ unit: UInt16) -> Bool {
        unit >= 48 && unit <= 57
    }

    private static func isPathUnit(_ unit: UInt16) -> Bool {
        isDigit(unit) || (unit >= 65 && unit <= 90) || (unit >= 97 && unit <= 122)
            || pathMarks.contains(unit)
    }

    /// Where the `:line`, `:line:column` or `:line-line` at `at` ends; `at` without one.
    private static func lineEnd(_ units: [UInt16], from at: Int) -> Int {
        func digits(from start: Int) -> Int {
            var index = start
            while index < units.count, isDigit(units[index]) {
                index += 1
            }
            return index
        }
        guard at < units.count, units[at] == colon else { return at }
        let line = digits(from: at + 1)
        guard line > at + 1 else { return at }
        guard line < units.count, units[line] == colon || units[line] == dash else { return line }
        let second = digits(from: line + 1)
        return second == line + 1 ? line : second
    }

    /// The text without a `:line`, `:line:column` or `:line-line` at its end.
    private static func withoutLine(_ text: String) -> String {
        let units = Array(text.utf16)
        var index = units.count
        func back() -> Bool {
            let start = index
            while index > 0, isDigit(units[index - 1]) {
                index -= 1
            }
            return index < start
        }
        func prefix(_ end: Int) -> String {
            String(decoding: units[..<end], as: UTF16.self)
        }
        guard back(), index > 0 else { return text }
        let mark = units[index - 1]
        if mark == colon {
            let end = index - 1
            index = end
            return back() && index > 0 && units[index - 1] == colon
                ? prefix(index - 1) : prefix(end)
        }
        guard mark == dash else { return text }
        index -= 1
        return back() && index > 0 && units[index - 1] == colon ? prefix(index - 1) : text
    }

    private static func hasScheme(_ text: String) -> Bool {
        guard let colon = text.firstIndex(of: ":"), let first = text.first, first.isASCII,
            first.isLetter
        else {
            return false
        }
        return text[..<colon].allSatisfy {
            $0.isASCII && ($0.isLetter || $0.isNumber || "+.-".contains($0))
        }
    }

    private static func nameOf(_ path: String) -> String {
        path.lastIndex(of: "/").map { String(path[path.index(after: $0)...]) } ?? path
    }

    private static func extensionOf(_ name: String) -> String? {
        guard let dot = name.lastIndex(of: "."), dot != name.startIndex else { return nil }
        return name[name.index(after: dot)...].lowercased()
    }

    /// Whether the first folder reads as a site: `example.com/a.md`.
    private static func startsWithHost(_ path: String) -> Bool {
        guard let slash = path.firstIndex(of: "/") else { return false }
        let first = String(path[..<slash])
        guard !first.hasPrefix("."), first.contains(".") else { return false }
        return !common.contains(extensionOf(first) ?? "")
    }

    private static func looksLikeFile(_ path: String) -> Bool {
        guard !path.isEmpty, !path.hasPrefix("//"), !path.hasPrefix("~"),
            let ext = extensionOf(nameOf(path))
        else {
            return false
        }
        if !path.contains("/") {
            return common.contains(ext) && !names.contains(path.lowercased())
        }
        let plain = ext.utf8.allSatisfy { ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 122) }
        let letter = ext.utf8.contains { $0 >= 97 && $0 <= 122 }
        return (1...12).contains(ext.utf8.count) && plain && letter && !startsWithHost(path)
    }

    // MARK: Opening

    /// The real path of the regular file `path` names inside the folder `root`, with `..` and
    /// links resolved so that neither can lead out of it; nil for anything else.
    public static func resolve(_ path: String, in root: String) -> String? {
        guard root.hasPrefix("/"), let folder = realPath(root), folder != "/" else { return nil }
        let given = path.hasPrefix("/") ? path : root + "/" + path
        guard let file = realPath(given), file.hasPrefix(folder + "/"),
            let attributes = try? FileManager.default.attributesOfItem(atPath: file),
            attributes[.type] as? FileAttributeType == .typeRegular
        else {
            return nil
        }
        return file
    }

    private static func realPath(_ path: String) -> String? {
        guard let resolved = realpath(path, nil) else { return nil }
        defer { free(resolved) }
        return String(cString: resolved)
    }
}
