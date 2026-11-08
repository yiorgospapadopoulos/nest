import Foundation

/// How full a chat's context gets before its engine compacts it by itself (B146). Sessions,
/// pixies and the agent defaults hold it as `compact_at` tokens, nil for Auto; updates send
/// `"auto"` or the number.
public enum CompactAt: Hashable, Sendable, Encodable {
    /// The engine's own behaviour.
    case auto
    case tokens(Int)

    /// What the menus offer, Auto first.
    public static let choices: [CompactAt] =
        [.auto] + [100_000, 300_000, 400_000, 700_000, 1_000_000].map(CompactAt.tokens)

    /// A stored `compact_at`.
    public init(_ tokens: Int?) {
        self = tokens.map(CompactAt.tokens) ?? .auto
    }

    /// What a session, pixie or default stores: nil for Auto.
    public var tokens: Int? {
        if case .tokens(let count) = self { count } else { nil }
    }

    /// "Auto", "100k", "1M".
    public var label: String {
        tokens.map(UsageText.tokens) ?? "Auto"
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .auto: try container.encode("auto")
        case .tokens(let count): try container.encode(count)
        }
    }
}
