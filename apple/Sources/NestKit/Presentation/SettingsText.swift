import Foundation

/// The words and numbers of Settings > General > Storage (B81).
public enum StorageText {
    /// "540 bytes", "12 KB", "820 MB", "1.4 GB"; in thousands, as Finder counts.
    public static func bytes(_ count: Int) -> String {
        let value = Double(count)
        switch count {
        case ..<1_000: return "\(count) bytes"
        case ..<1_000_000: return "\(Int((value / 1_000).rounded())) KB"
        case ..<1_000_000_000: return "\(Int((value / 1_000_000).rounded())) MB"
        default: return String(format: "%.1f GB", value / 1_000_000_000)
        }
    }

    public enum Part: Sendable, Hashable, CaseIterable {
        case chats, attachments, artifacts, other

        public var name: String {
            switch self {
            case .chats: "Chats"
            case .attachments: "Attachments"
            case .artifacts: "Artifacts"
            case .other: "Other"
            }
        }
    }

    /// Each part's share of the total, for the space used bar; none while it is empty.
    public static func shares(_ usage: StorageUsage) -> [(part: Part, share: Double)] {
        guard usage.totalBytes > 0 else { return [] }
        let total = Double(usage.totalBytes)
        return parts(usage).map { ($0.part, Double($0.bytes) / total) }
    }

    /// A share as a whole percent: "<1%" above zero but under 1%, "0%" at zero.
    public static func share(_ share: Double) -> String {
        if share > 0 && share < 0.01 {
            return "<1%"
        }
        return "\(Int((share * 100).rounded()))%"
    }

    /// The ledger's lines (B86): each part with its size and share, all four even at zero.
    public static func ledger(_ usage: StorageUsage) -> [(part: Part, size: String, share: String)]
    {
        let total = Double(usage.totalBytes)
        return parts(usage).map { part, bytes in
            (part, Self.bytes(bytes), share(total > 0 ? Double(bytes) / total : 0))
        }
    }

    /// The bar's segments at a width: parts above zero, `gap` apart, none narrower than
    /// `minimum`; the largest takes what the others leave, so they fill the width exactly.
    public static func segments(
        _ shares: [(part: Part, share: Double)], width: Double, gap: Double, minimum: Double
    ) -> [(part: Part, width: Double)] {
        let shown = shares.filter { $0.share > 0 }
        guard let largest = shown.max(by: { $0.share < $1.share })?.part else { return [] }
        let available = width - gap * Double(shown.count - 1)
        let others = shown.filter { $0.part != largest }
            .map { ($0.part, max(minimum, $0.share * available)) }
        let rest = available - others.reduce(0) { $0 + $1.1 }
        return shown.map { item in
            (item.part, others.first { $0.0 == item.part }?.1 ?? rest)
        }
    }

    private static func parts(_ usage: StorageUsage) -> [(part: Part, bytes: Int)] {
        [
            (.chats, usage.chatsBytes), (.attachments, usage.attachmentsBytes),
            (.artifacts, usage.artifactsBytes), (.other, usage.otherBytes),
        ]
    }

    /// Archive chats idle for: Never, 7, 30 or 90 days.
    public static let archiveChoices: [Int?] = [nil, 7, 30, 90]

    /// "Never", "1 day", "30 days".
    public static func archiveLabel(_ days: Int?) -> String {
        switch days {
        case nil: "Never"
        case 1: "1 day"
        case let days?: "\(days) days"
        }
    }

    /// Where an attachment came from: its chat, or none any more.
    public static func source(of attachment: LargeAttachment) -> String {
        attachment.sessionTitle ?? (attachment.sessionID == nil ? "No chat" : "Untitled chat")
    }
}

/// The choices of Settings > Pixies (B81).
public enum PixieSettingsText {
    public static let maxRunningChoices = [1, 2, 3, 5]
    public static let maxPerDayChoices = [3, 5, 10, 20]
    public static let habitUsageChoices = [70, 80, 90, 100]

    /// The choices, with a value the daemon holds that is not one of them, in order.
    public static func choices(_ base: [Int], including value: Int?) -> [Int] {
        guard let value, !base.contains(value) else { return base }
        return (base + [value]).sorted()
    }
}

/// The words of Settings > Accounts (B81).
public enum AccountText {
    /// "Max plan, Team org", or what Claude Code reported of the two.
    public static func claudeDetail(_ login: ClaudeLogin) -> String? {
        let parts = [login.plan.map { "\($0) plan" }, login.organization].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: ", ")
    }

    public static func githubState(_ state: GitHubLoginState) -> String {
        switch state {
        case .signedIn: "Signed in"
        case .signedOut: "Signed out"
        case .unavailable: "gh is not installed"
        case .unknown: "Unknown"
        }
    }
}
