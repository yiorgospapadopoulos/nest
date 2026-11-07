import Foundation

/// One check of `GET /api/setup/checks` (B130), as the guide, Check Nest and `nest doctor`
/// show it. The daemon's list is the single source; the app only fills in what it alone can
/// answer (`SystemAnswers`).
public struct SetupCheck: Codable, Sendable, Hashable, Identifiable {
    public enum State: String, UnknownSafeEnum {
        case ok, missing, warning
        case notApplicable = "not_applicable"
        case unknown
    }

    /// What sorts it out: a command to paste, or a page to open.
    public struct Fix: Codable, Sendable, Hashable {
        public enum Kind: String, UnknownSafeEnum {
            case command, link, unknown
        }

        public var kind: Kind
        public var value: String

        public init(kind: Kind, value: String) {
            self.kind = kind
            self.value = value
        }
    }

    /// How much a missing check matters: Nest cannot run, it works less well, or it is extra.
    public enum Importance: String, UnknownSafeEnum {
        case required, recommended, optional, unknown
    }

    public var id: String
    public var title: String
    public var state: State
    /// What is wrong and what to do; empty when there is nothing to say.
    public var message: String
    /// The short answer beside a title, such as a version.
    public var detail: String?
    public var fix: Fix?
    public var importance: Importance
    /// How far a check with several steps has got, such as Tailscale's (`TailscaleStage`).
    public var stage: String?

    public init(
        id: String, title: String, state: State, message: String = "", detail: String? = nil,
        fix: Fix? = nil, importance: Importance = .recommended, stage: String? = nil
    ) {
        self.id = id
        self.title = title
        self.state = state
        self.message = message
        self.detail = detail
        self.fix = fix
        self.importance = importance
        self.stage = stage
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, state, message, detail, fix, importance, stage
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        title = try container.decode(String.self, forKey: .title)
        state = try container.decode(State.self, forKey: .state)
        message = try container.decodeIfPresent(String.self, forKey: .message) ?? ""
        detail = try container.decodeIfPresent(String.self, forKey: .detail)
        fix = try container.decodeIfPresent(Fix.self, forKey: .fix)
        importance =
            try container.decodeIfPresent(Importance.self, forKey: .importance) ?? .recommended
        stage = try container.decodeIfPresent(String.self, forKey: .stage)
    }

    /// Where it goes in Check Nest, lowest first, as the daemon's `Check.rank`: what stops
    /// Nest, then what it lacks, then warnings, then the optional, then what is fine. Worked
    /// out here, since the app's own answers change a check's state.
    public var rank: Int {
        switch state {
        case .missing:
            switch importance {
            case .required: 0
            case .optional: 3
            case .recommended, .unknown: 1
            }
        case .warning: 2
        case .notApplicable, .unknown: 3
        case .ok: 4
        }
    }

    /// Check Nest's one list, what matters most on top; equal ranks keep the daemon's order.
    public static func ranked(_ checks: [SetupCheck]) -> [SetupCheck] {
        checks.filter(\.isShown).enumerated()
            .sorted { ($0.element.rank, $0.offset) < ($1.element.rank, $1.offset) }
            .map(\.element)
    }

    /// A check with nothing to say, such as the Secret Service on a Mac, does not apply here.
    public var isShown: Bool {
        state != .notApplicable || !message.isEmpty || detail != nil || fix != nil
    }
}

/// `GET /api/setup/checks`.
struct SetupChecks: Codable, Sendable {
    var checks: [SetupCheck]
}

/// The body of `POST /api/setup/report`: the app's own answers for the checks only it can
/// make, which replace the daemon's in the report.
struct SetupReportAsk: Encodable {
    var checks: [SetupCheck]
}

/// `POST /api/setup/report`: the bug report with secrets removed, and the file it was saved
/// as. Nothing is sent anywhere: `issueURL` is a new GitHub issue with the report filled in,
/// for the user to read and submit.
public struct SetupReport: Codable, Sendable, Hashable {
    public var path: String
    public var text: String
    public var issueURL: String
    /// The report was too long for the address: the issue asks for the file instead.
    public var attachFile: Bool

    public init(path: String, text: String, issueURL: String = "", attachFile: Bool = false) {
        self.path = path
        self.text = text
        self.issueURL = issueURL
        self.attachFile = attachFile
    }

    private enum CodingKeys: String, CodingKey {
        case path, text
        case issueURL = "issue_url"
        case attachFile = "attach_file"
    }
}
