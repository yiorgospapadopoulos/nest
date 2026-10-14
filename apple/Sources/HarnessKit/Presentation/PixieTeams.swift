import Foundation

// Teams in the Pixies list and pixies in the composer's `@` list; the same rules and words
// as the iPhone (B40, D056).

extension Pixie {
    /// It is passed to chats of this repo as a subagent: not hidden, with project access,
    /// and assigned to every project or to this one (the daemon's rule).
    public func isAvailable(inRepo repo: String) -> Bool {
        !hidden && projectAccess != .noAccess && (projects?.contains(repo) ?? true)
    }
}

/// A team in the Pixies list, with its listed members in pixie order.
public struct PixieTeamSection: Sendable, Hashable, Identifiable {
    public let team: PixieTeam
    public let members: [Pixie]

    public var id: String { team.id }

    public func isLeader(_ pixie: Pixie) -> Bool {
        team.leaderID == pixie.id
    }
}

/// The Pixies list: teams in their order, then the pixies with no team.
public struct PixieListSections: Sendable, Hashable {
    public let teams: [PixieTeamSection]
    /// Pixies with no team, or one not known yet.
    public let loose: [Pixie]

    /// The ids of the pixies in the same section as this one, in order: Move Up and Move
    /// Down stay within it.
    public func neighbors(of id: String) -> [String] {
        let lists = teams.map(\.members) + [loose]
        return lists.first { $0.contains { $0.id == id } }?.map(\.id) ?? []
    }
}

public enum PixieListLayout {
    /// `listed` are the pixies the list shows, in pixie order.
    public static func sections(_ listed: [Pixie], teams: [PixieTeam]) -> PixieListSections {
        let ordered = teams.sorted { ($0.position, $0.id) < ($1.position, $1.id) }
        let known = Set(ordered.map(\.id))
        return PixieListSections(
            teams: ordered.map { team in
                PixieTeamSection(team: team, members: listed.filter { $0.teamID == team.id })
            },
            loose: listed.filter { pixie in pixie.teamID.map { !known.contains($0) } ?? true })
    }
}

/// A pixie or a team offered in the composer's `@` list.
public enum PixieMention: Sendable, Hashable {
    /// With its members available in the chat.
    case team(PixieTeam, members: [Pixie])
    /// With its soul's first line, once read.
    case pixie(Pixie, soul: String?)

    /// What follows the "@": the pixie's slug or the team's handle.
    public var token: String {
        switch self {
        case .team(let team, _): team.handle
        case .pixie(let pixie, _): pixie.slug
        }
    }

    public var name: String {
        switch self {
        case .team(let team, _): team.name
        case .pixie(let pixie, _): pixie.name
        }
    }

    public var id: String {
        switch self {
        case .team(let team, _): "team:\(team.id)"
        case .pixie(let pixie, _): "pixie:\(pixie.id)"
        }
    }
}

public enum PixieMentions {
    /// What a chat of `repo` may call: the teams whose leader is available there, with
    /// their available members, then the available pixies, each in its order. A team
    /// with no members has no leader and is left out.
    public static func available(
        pixies: [Pixie], teams: [PixieTeam], repo: String, souls: [String: String]
    ) -> [PixieMention] {
        let callable = pixies.filter { $0.isAvailable(inRepo: repo) }
        let teamMentions = teams.sorted { ($0.position, $0.id) < ($1.position, $1.id) }
            .compactMap { team -> PixieMention? in
                let members = callable.filter { $0.teamID == team.id }
                guard members.contains(where: { $0.id == team.leaderID }) else { return nil }
                return .team(team, members: members)
            }
        return teamMentions + callable.map { .pixie($0, soul: souls[$0.id]) }
    }

    /// Those whose handle, slug or name contains what was typed after the "@".
    public static func matching(_ mentions: [PixieMention], query: String) -> [PixieMention] {
        guard !query.isEmpty else { return mentions }
        let query = query.lowercased()
        return mentions.filter {
            $0.token.lowercased().contains(query) || $0.name.lowercased().contains(query)
        }
    }
}

public enum PixieSoul {
    /// The first line of a soul with text on it, trimmed.
    public static func firstLine(_ text: String) -> String? {
        text.split(separator: "\n").lazy
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .first { !$0.isEmpty }
    }
}

/// A question the Pixies list asks before acting: a name or handle to type, or a delete
/// to confirm.
public enum PixiePrompt: Sendable, Hashable {
    case newTeam
    case renameTeam(String)
    case teamHandle(String)
    case deletePixie(String)
    case deleteTeam(String)

    /// It asks for text rather than a confirmation.
    public var isTyped: Bool {
        switch self {
        case .newTeam, .renameTeam, .teamHandle: true
        case .deletePixie, .deleteTeam: false
        }
    }

    /// The text the field starts with, shown selected: the team's current name or
    /// handle; nothing for a new team.
    public func startText(teams: [PixieTeam]) -> String {
        switch self {
        case .renameTeam(let id): teams.first { $0.id == id }?.name ?? ""
        case .teamHandle(let id): teams.first { $0.id == id }?.handle ?? ""
        default: ""
        }
    }

    public var title: String {
        switch self {
        case .newTeam: "New team"
        case .renameTeam: "Rename team"
        case .teamHandle: "Change handle"
        case .deletePixie: "Delete pixie"
        case .deleteTeam: "Delete team"
        }
    }

    /// The field's placeholder.
    public var field: String {
        if case .teamHandle = self { "Handle" } else { "Name" }
    }

    public var action: String {
        switch self {
        case .newTeam: "Create"
        case .renameTeam: "Rename"
        case .teamHandle: "Save"
        case .deletePixie, .deleteTeam: "Delete"
        }
    }

    /// A line under the field, for the handle's rules.
    public var note: String? {
        guard case .teamHandle = self else { return nil }
        return "Lowercase letters, digits and dashes; chats call the team with it."
    }
}

/// A Delete action's confirmation: the question and what it means.
public struct PixieConfirmation: Sendable, Hashable {
    public let title: String
    public let message: String

    /// The whole sentence, as the iPhone shows it.
    public var text: String { "\(title) \(message)" }
}

/// The confirmations of the Delete actions, word for word as on the iPhone.
public enum PixieConfirm {
    public static func deletePixie(_ name: String) -> PixieConfirmation {
        PixieConfirmation(
            title: "Delete \(name)?",
            message: "Its chat, soul and memory go too. This can't be undone.")
    }

    public static func deleteTeam(_ name: String) -> PixieConfirmation {
        PixieConfirmation(title: "Delete \(name)?", message: "Its pixies stay, without a team.")
    }
}

/// Agent calls of pixies in a chat's transcript (B40).
public enum PixieCalls {
    /// The slugs the transcript shows as pixie calls.
    public static func slugs(_ pixies: [Pixie]) -> Set<String> {
        Set(pixies.map(\.slug))
    }

    /// The pixie an agent call ran, matched by its subagent name.
    public static func pixie(of call: ToolCall, among pixies: [Pixie]) -> Pixie? {
        guard let slug = call.subagentType else { return nil }
        return pixies.first { $0.slug == slug }
    }
}

/// A pixie or team mention in a sent message, drawn in the pixie's colour.
public struct MentionHighlight: Sendable, Hashable {
    /// In UTF-16 units, as text views count.
    public let range: NSRange
    /// `#RRGGBB`.
    public let color: String
}

public enum MentionHighlights {
    /// "@name" as a whole token, as the daemon reads mentions: at the start or after
    /// whitespace, the name running to the first character that is not a word character
    /// or a hyphen.
    private static let token = try! NSRegularExpression(pattern: #"(?<!\S)@([\w-]+)"#)

    /// The mentions of current pixies (in their colour) and teams (in their leader's;
    /// a team with no leader stays plain). Unknown names stay plain.
    public static func find(in text: String, pixies: [Pixie], teams: [PixieTeam])
        -> [MentionHighlight]
    {
        func color(of name: String) -> String? {
            if let pixie = pixies.first(where: { $0.slug == name }) {
                return pixie.color
            }
            let leader = teams.first { $0.handle == name }?.leaderID
            return pixies.first { $0.id == leader }?.color
        }
        let whole = NSRange(text.startIndex..., in: text)
        return token.matches(in: text, range: whole).compactMap { match in
            let name = (text as NSString).substring(with: match.range(at: 1))
            return color(of: name).map { MentionHighlight(range: match.range, color: $0) }
        }
    }
}
