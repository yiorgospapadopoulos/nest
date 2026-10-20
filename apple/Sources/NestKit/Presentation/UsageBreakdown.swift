import Foundation

/// The usage popover's Details: a period's tokens by engine, by who spent them, by kind and
/// by project, with the usage checks counted apart.
public struct UsageBreakdown: Sendable, Equatable {
    public struct Row: Sendable, Equatable {
        public let label: String
        public let value: String
        public let share: String
    }

    public struct Project: Sendable, Equatable, Identifiable {
        public let name: String
        public let value: String
        /// The bar's length, the largest entry being 1.
        public let fraction: Double

        public var id: String { name }
    }

    /// Projects shown by name; the rest share one "Others (n)" entry.
    static let namedProjects = 4

    public let total: String
    /// Claude, then each other engine (B91); empty while only one engine is known and used.
    public let engines: [Row]
    /// Chats and Subagents.
    public let who: [Row]
    /// Cache read, Cache write, Output and Input.
    public let kinds: [Row]
    public let projects: [Project]
    /// "12 usage checks, 5k tokens, not counted above"; nil when there were none.
    public let probes: String?

    /// `engines` are the engines the app knows, for their names and to list one without
    /// tokens in the period.
    public init(_ period: UsagePeriod, engines known: [ProviderInfo] = []) {
        let tokens = period.tokens
        func row(_ label: String, _ count: Int) -> Row {
            Row(
                label: label, value: UsageText.tokens(count),
                share: UsageText.share(count, of: tokens.total))
        }
        total = UsageText.tokens(tokens.total)
        var names = [ProviderInfo.claude] + known.map(\.name).filter { $0 != ProviderInfo.claude }
        var used: [String: Int] = [:]
        for engine in period.engines {
            if !names.contains(engine.provider) {
                names.append(engine.provider)
            }
            used[engine.provider, default: 0] += engine.tokens
        }
        engines =
            names.count > 1
            ? names.map { name in
                let label = known.first { $0.name == name }?.displayName ?? name.capitalized
                return row(label, used[name] ?? 0)
            } : []
        who = [
            row("Chats", tokens.total - period.subagents.total),
            row("Subagents", period.subagents.total),
        ]
        kinds = [
            row("Cache read", tokens.cacheReadInputTokens),
            row("Cache write", tokens.cacheCreationInputTokens),
            row("Output", tokens.outputTokens),
            row("Input", tokens.inputTokens),
        ]
        var entries = period.projects.prefix(Self.namedProjects).map { ($0.name, $0.tokens) }
        let rest = period.projects.dropFirst(Self.namedProjects)
        if !rest.isEmpty {
            entries.append(("Others (\(rest.count))", rest.map(\.tokens).reduce(0, +)))
        }
        let peak = max(entries.map(\.1).max() ?? 0, 1)
        projects = entries.map { name, count in
            Project(
                name: name, value: UsageText.tokens(count),
                fraction: Double(count) / Double(peak))
        }
        probes = UsageText.probes(period.probes)
    }
}
