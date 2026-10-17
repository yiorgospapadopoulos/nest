import Foundation

// What the Pixies tab shows and offers; the same choices and words as the iPhone (D072).

extension Pixie {
    /// A pixie chat's repo is "pixie:<pixie id>".
    public static let repoPrefix = "pixie:"

    /// The pixie a chat's repo names; nil for a project's chat.
    public static func id(ofRepo repo: String) -> String? {
        guard repo.hasPrefix(repoPrefix) else { return nil }
        let id = String(repo.dropFirst(repoPrefix.count))
        return id.isEmpty ? nil : id
    }
}

extension Pixie {
    /// The daemon's answer to a model change took this pixie out of Auto, as it does for a
    /// model without Auto mode; the app says so. `self` is the pixie before the change.
    public func droppedAuto(by change: UpdatePixieRequest, saved: Pixie) -> Bool {
        permissionMode == .auto && change.permissionMode == nil
            && (change.model != nil || change.clearsModel) && saved.permissionMode != .auto
    }
}

extension Mascot {
    /// The mascots to pick from, in the order of `design/mascots.toml`.
    public static var choices: [Mascot] { allCases.filter { $0 != .unknown } }

    /// Its pixel grid, top row first; "#" is filled. Empty for an unknown mascot.
    public var rows: [String] { MascotSprites.rows[rawValue] ?? [] }
}

/// The Add menu of a pixie's Skills (B85): the skills not chosen yet, standalone ones at
/// the top and one group per plugin, each in name order.
public struct PixieSkillMenu: Sendable, Hashable {
    public let standalone: [PixieSkillChoice]
    public let groups: [PixieSkillGroup]
    /// Whether any skill was offered at all.
    private let anyInstalled: Bool

    public init(choices: [PixieSkillChoice], chosen: [String]) {
        anyInstalled = !choices.isEmpty
        let open = choices.filter { !chosen.contains($0.name) }.sorted { $0.name < $1.name }
        standalone = open.filter { $0.plugin == nil }
        let byPlugin = open.compactMap { skill in skill.plugin.map { ($0, [skill]) } }
        groups = Dictionary(byPlugin, uniquingKeysWith: +)
            .map { PixieSkillGroup(plugin: $0.key, skills: $0.value) }
            .sorted { $0.plugin < $1.plugin }
    }

    public var isEmpty: Bool { standalone.isEmpty && groups.isEmpty }

    /// What the menu says when it offers none; nil when it offers some.
    public var emptyText: String? {
        guard isEmpty else { return nil }
        return anyInstalled ? "Every installed skill is added" : "No skills installed"
    }
}

/// One plugin's skills in the Add menu.
public struct PixieSkillGroup: Sendable, Hashable, Identifiable {
    public let plugin: String
    public let skills: [PixieSkillChoice]

    public var id: String { plugin }
}

extension ProjectAccess {
    public static var choices: [ProjectAccess] { [.edit, .read, .noAccess] }

    public var label: String {
        switch self {
        case .edit: "Edit"
        case .read: "Read only"
        case .noAccess: "None"
        case .unknown: "Unknown"
        }
    }

    public var summary: String {
        switch self {
        case .edit: "Reads and edits its projects like any chat"
        case .read: "Reads its projects, writes only in its own folder"
        case .noAccess: "Works only in its own folder"
        case .unknown: ""
        }
    }
}

extension Autonomy {
    /// What its Nest tools may do (B41); the daemon checks it on every call.
    public static var choices: [Autonomy] { [.observe, .message, .start, .answer] }

    public var label: String {
        switch self {
        case .observe: "Observe"
        case .message: "Message"
        case .start: "Start"
        case .answer: "Answer"
        case .unknown: "Unknown"
        }
    }

    public var summary: String {
        switch self {
        case .observe: "Reads chats in its projects."
        case .message: "Also writes to them, nudges or stops them."
        case .start: "Also starts chats in their own worktree."
        case .answer: "Also answers approvals, questions and plans in chats it started."
        case .unknown: ""
        }
    }
}

/// A pixie's `#RRGGBB` colour.
public enum PixieColor {
    /// The colour a new pixie gets.
    public static let standard = "#8B7CF6"

    /// The colour's channels; nil for text that is not `#RRGGBB`.
    public static func rgba(_ hex: String) -> RGBA? {
        let digits = hex.dropFirst()
        guard hex.first == "#", digits.count == 6, digits.allSatisfy(\.isHexDigit),
            let value = Int(digits, radix: 16)
        else { return nil }
        func channel(_ shift: Int) -> Double { Double((value >> shift) & 0xFF) / 255 }
        return RGBA(red: channel(16), green: channel(8), blue: channel(0), alpha: 1)
    }

    /// Channels from 0 to 1 as `#RRGGBB`, in capitals as the presets are written.
    public static func hex(red: Double, green: Double, blue: Double) -> String {
        func byte(_ value: Double) -> String {
            String(format: "%02X", Int((min(max(value, 0), 1) * 255).rounded()))
        }
        return "#" + byte(red) + byte(green) + byte(blue)
    }

    /// A colour none of the ten presets has: the custom dot is the chosen one.
    public static func isCustom(_ hex: String) -> Bool {
        !PixieColors.presets.contains(hex.uppercased())
    }
}

/// A one-click starter while the user has no pixies; nothing is created without the click.
public struct PixieTemplate: Sendable, Hashable {
    public let name: String
    public let mascot: Mascot
    /// The first text of its `SOUL.md`.
    public let soul: String

    /// Reviewer and Tester, with the iPhone's starter souls.
    public static let all = [
        PixieTemplate(
            name: "Reviewer", mascot: .owl,
            soul:
                "You review code changes. Look for bugs, missing tests and unclear names first, "
                + "style last. Say what you checked, then list problems by severity with file and line."
        ),
        PixieTemplate(
            name: "Tester", mascot: .robot,
            soul:
                "You test changes. Find how the project runs its tests, run them, add missing "
                + "cases for the change, and report what passed, what failed and why."),
    ]

    public var request: CreatePixieRequest {
        CreatePixieRequest(name: name, mascot: mascot, soul: soul)
    }
}

/// A fact of a pixie's `MEMORY.md`: a line written as "- YYYY-MM-DD: <fact>".
public struct PixieFact: Sendable, Hashable, Identifiable {
    /// The line's index in the file.
    public let line: Int
    /// Empty for a line written without one.
    public let date: String
    public let text: String

    public var id: Int { line }
}

/// Reading and changing the facts of `MEMORY.md`, as the iPhone does.
public enum PixieMemory {
    public static func isFact(_ line: Substring) -> Bool {
        line.hasPrefix("- ")
    }

    public static func facts(in text: String) -> [PixieFact] {
        text.split(separator: "\n", omittingEmptySubsequences: false).enumerated().compactMap {
            index, line in
            guard isFact(line) else { return nil }
            if line.prefixMatch(of: #/- \d{4}-\d{2}-\d{2}: /#) != nil {
                return PixieFact(
                    line: index, date: String(line.dropFirst(2).prefix(10)),
                    text: String(line.dropFirst(14)))
            }
            return PixieFact(line: index, date: "", text: String(line.dropFirst(2)))
        }
    }

    /// The text with a dated fact line at the end.
    public static func adding(_ fact: String, to text: String, on day: String) -> String {
        let base = text.isEmpty || text.hasSuffix("\n") ? text : text + "\n"
        return base + "- \(day): \(fact)\n"
    }

    /// The text without the line at `index`.
    public static func removing(line index: Int, from text: String) -> String {
        var lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        if lines.indices.contains(index) {
            lines.remove(at: index)
        }
        return lines.joined(separator: "\n")
    }

    /// The day in the user's time zone, as a fact line writes it.
    public static func day(of date: Date, calendar: Calendar = .current) -> String {
        String(
            format: "%04d-%02d-%02d", calendar.component(.year, from: date),
            calendar.component(.month, from: date), calendar.component(.day, from: date))
    }

    /// "1 fact", "3 facts".
    public static func count(_ text: String) -> String {
        let count = facts(in: text).count
        return "\(count) \(count == 1 ? "fact" : "facts")"
    }
}
