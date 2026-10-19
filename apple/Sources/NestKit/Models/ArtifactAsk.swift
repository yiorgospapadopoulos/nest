import Foundation
import UniformTypeIdentifiers

/// `POST /api/artifacts/{id}/ask` (B88): a page's small request to Claude.
struct AskArtifactRequest: Encodable {
    let prompt: String
    let system: String?
}

/// Claude's answer to a page, and how many of today's asks are left. The daemon's limit is
/// 20 unless it says otherwise.
public struct ArtifactAnswer: Decodable, Sendable, Hashable {
    public static let defaultLimit = 20
    public let text: String
    public let remaining: Int
    public let limit: Int

    public init(text: String, remaining: Int, limit: Int) {
        self.text = text
        self.remaining = remaining
        self.limit = limit
    }

    enum CodingKeys: String, CodingKey {
        case text, remaining, limit
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        text = try container.decode(String.self, forKey: .text)
        remaining = try container.decode(Int.self, forKey: .remaining)
        limit = try container.decodeIfPresent(Int.self, forKey: .limit) ?? Self.defaultLimit
    }
}

/// `GET /api/artifacts/{id}/ask`: today's asks of the artifact and whether asking is on.
public struct ArtifactAskStatus: Decodable, Sendable, Hashable {
    public let used: Int
    public let limit: Int
    public let remaining: Int
    /// When today's count starts again.
    public let resetsAt: Date?
    public let enabled: Bool

    public init(used: Int, limit: Int, remaining: Int, resetsAt: Date?, enabled: Bool) {
        self.used = used
        self.limit = limit
        self.remaining = remaining
        self.resetsAt = resetsAt
        self.enabled = enabled
    }

    enum CodingKeys: String, CodingKey {
        case used, limit, remaining, enabled
        case resetsAt = "resets_at"
    }
}

/// `artifact.ask`: an ask for the artifact started or finished, on any device.
public struct ArtifactAskEvent: Decodable, Sendable, Hashable {
    public enum State: String, UnknownSafeEnum {
        case started, finished
        case unknown
    }

    public let artifactID: String
    public let state: State
    public let remaining: Int
    public let limit: Int

    public init(artifactID: String, state: State, remaining: Int, limit: Int) {
        self.artifactID = artifactID
        self.state = state
        self.remaining = remaining
        self.limit = limit
    }

    enum CodingKeys: String, CodingKey {
        case state, remaining, limit
        case artifactID = "artifact_id"
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        artifactID = try container.decode(String.self, forKey: .artifactID)
        state = try container.decode(State.self, forKey: .state)
        remaining = try container.decode(Int.self, forKey: .remaining)
        limit =
            try container.decodeIfPresent(Int.self, forKey: .limit) ?? ArtifactAnswer.defaultLimit
    }
}

/// Today's asks of one artifact, for the reader's line.
public struct ArtifactAskCount: Sendable, Hashable {
    public let remaining: Int
    public let limit: Int

    public init(remaining: Int, limit: Int) {
        self.remaining = remaining
        self.limit = limit
    }

    /// "3 of 20 asks today".
    public var text: String {
        "\(min(max(limit - remaining, 0), limit)) of \(limit) asks today"
    }
}

/// What `nest.usage()` answers: the limit windows and today's and this week's tokens, the
/// numbers of Nest's Usage page.
public enum ArtifactPageUsage {
    public static func value(limits: UsageLimits?, today: UsagePeriod, week: UsagePeriod)
        -> ArtifactBridge.Value
    {
        func window(_ window: LimitWindow?) -> ArtifactBridge.Value {
            guard let window else { return .null }
            return .object([
                "utilization": .number(window.utilization),
                "resets_at": window.resetsAt.map { .string($0.formatted(.iso8601)) } ?? .null,
            ])
        }
        func period(_ period: UsagePeriod) -> ArtifactBridge.Value {
            .object([
                "tokens": .number(Double(period.tokens.total)),
                "sessions": .number(Double(period.sessions)),
            ])
        }
        return .object([
            "limits": .object([
                "five_hour": window(limits?.fiveHour), "seven_day": window(limits?.sevenDay),
            ]),
            "today": period(today), "week": period(week),
        ])
    }
}

/// `<input type=file accept=...>` on the Mac: WebKit's open panel parameters do not carry
/// the accept list, so a script in Nest's own content world, which the page cannot reach,
/// notes the accept list of the file input last clicked (by the user, a label or the page's
/// `input.click()`), `script` reads it back, and the open panel is narrowed to its types.
public enum ArtifactOpenPanel {
    /// The content world both scripts run in.
    public static let world = "nest-host"
    /// Runs at document start in `world`.
    public static let watchScript =
        "document.addEventListener(\"click\",function(e){var t=e.target;if(t&&t.tagName===\"INPUT\"&&t.type===\"file\")window.__nestAccept=t.accept||\"\"},true)"
    /// The noted accept list, or null.
    public static let script =
        "window.__nestAccept===undefined?null:window.__nestAccept"

    /// The types an accept list names, nil (every file) when it names none or one this
    /// cannot read, so a page never loses a file it accepts.
    public static func types(accept: String?) -> [UTType]? {
        let tokens = (accept ?? "").split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
            .filter { !$0.isEmpty }
        guard !tokens.isEmpty else { return nil }
        var types: [UTType] = []
        for token in tokens {
            guard let type = type(token) else { return nil }
            types.append(type)
        }
        return types
    }

    private static func type(_ token: String) -> UTType? {
        if token.hasPrefix(".") {
            return UTType(filenameExtension: String(token.dropFirst()))
        }
        switch token {
        case "image/*": return .image
        case "audio/*": return .audio
        case "video/*": return .movie
        case "text/*": return .text
        default:
            // An unknown MIME type comes back as a made-up type no file has.
            return UTType(mimeType: token).flatMap { $0.isDynamic ? nil : $0 }
        }
    }
}
