import Foundation

/// A group of the tree under a chat's row (B46).
public enum ChatTreeGroup: String, Sendable, Hashable {
    case pixies, subagents

    public var title: String {
        switch self {
        case .pixies: "Pixies"
        case .subagents: "Subagents"
        }
    }
}

/// A row of the tree under a chat, joined to the chat by tree lines: a group's title, a
/// pixie, a team with its members, or a running subagent.
public struct ChatTreeRow: Sendable, Hashable, Identifiable {
    public enum Kind: Sendable, Hashable {
        case group(ChatTreeGroup)
        case pixie(Pixie, ChatPixieEntry)
        /// With its leader's colour, `#RRGGBB`, when it has a known leader.
        case team(PixieTeam, color: String?, ChatPixieEntry)
        case member(Pixie, leader: Bool, state: PixieCallState?, team: ChatPixieEntry)
        case subagent(TrackedAgent)
    }

    public let id: String
    public let kind: Kind
    /// Levels below the chat: 0 for a group's title, 1 for its entries, 2 for a team's
    /// members and subagents started by a subagent, and so on.
    public let depth: Int
    /// For each level above this row, outermost first: a line runs on past this row to
    /// a later sibling at that level.
    public let guides: [Bool]
    /// The last child of its parent, so its elbow ends the line.
    public let isLast: Bool
}

public enum ChatTree {
    /// The tree under a chat: "Pixies" with each entry of its group (a team with its
    /// members), then "Subagents" with its running subagents, those started by a
    /// subagent one level under it. The main agent and pixie calls (by their Agent call or
    /// their name) are not subagents here; pixies and teams no longer known are left out,
    /// and a group with nothing in it does not show.
    public static func rows(
        group: [ChatPixieEntry], agents: [TrackedAgent], pixies: [Pixie], teams: [PixieTeam]
    ) -> [ChatTreeRow] {
        var roots: [Node] = []
        let entries = group.compactMap { node(for: $0, pixies: pixies, teams: teams) }
        if !entries.isEmpty {
            roots.append(Node(id: "pixies", kind: .group(.pixies), children: entries))
        }
        let subagents = subagentNodes(agents, group: group, pixies: pixies)
        if !subagents.isEmpty {
            roots.append(Node(id: "subagents", kind: .group(.subagents), children: subagents))
        }
        var rows: [ChatTreeRow] = []
        flatten(roots, guides: [], into: &rows)
        return rows
    }

    /// A member's state in words; one the leader has not called yet says so.
    public static func label(of state: PixieCallState?) -> String {
        state?.label ?? "not called yet"
    }

    private struct Node {
        let id: String
        let kind: ChatTreeRow.Kind
        var children: [Node] = []
    }

    private static func node(for entry: ChatPixieEntry, pixies: [Pixie], teams: [PixieTeam])
        -> Node?
    {
        if entry.kind == .team {
            guard let team = teams.first(where: { $0.id == entry.teamID }) else { return nil }
            let members = entry.members.compactMap { member -> Node? in
                guard let pixie = pixies.first(where: { $0.id == member.pixieID }) else {
                    return nil
                }
                return Node(
                    id: "\(entry.id)/\(pixie.id)",
                    kind: .member(pixie, leader: member.leader, state: member.state, team: entry))
            }
            return Node(
                id: entry.id,
                kind: .team(team, color: team.leaderColor(among: pixies), entry),
                children: members)
        }
        guard let pixie = pixies.first(where: { $0.id == entry.pixieID }) else { return nil }
        return Node(id: entry.id, kind: .pixie(pixie, entry))
    }

    private static func subagentNodes(
        _ agents: [TrackedAgent], group: [ChatPixieEntry], pixies: [Pixie]
    ) -> [Node] {
        let calls = Set(group.flatMap(\.calls).map(\.toolUseID))
        let slugs = Set(pixies.map(\.slug))
        let shown = agents.filter { agent in
            !agent.isMain && agent.status == .running && !calls.contains(agent.id)
                && !slugs.contains(agent.name)
        }
        let ids = Set(shown.map(\.id))
        func children(of parent: String?) -> [Node] {
            shown.filter { agent in
                guard parent != nil else { return agent.parent.map { !ids.contains($0) } ?? true }
                return agent.parent == parent
            }
            .map { Node(id: $0.id, kind: .subagent($0), children: children(of: $0.id)) }
        }
        return children(of: nil)
    }

    private static func flatten(_ nodes: [Node], guides: [Bool], into rows: inout [ChatTreeRow]) {
        for (index, node) in nodes.enumerated() {
            let last = index == nodes.count - 1
            rows.append(
                ChatTreeRow(
                    id: node.id, kind: node.kind, depth: guides.count, guides: guides,
                    isLast: last))
            flatten(node.children, guides: guides + [!last], into: &rows)
        }
    }
}
