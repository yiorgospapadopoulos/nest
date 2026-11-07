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

    public var id: String
    public var title: String
    public var state: State
    /// What is wrong and what to do; empty when there is nothing to say.
    public var message: String
    /// The short answer beside a title, such as a version.
    public var detail: String?
    public var fix: Fix?

    public init(
        id: String, title: String, state: State, message: String = "", detail: String? = nil,
        fix: Fix? = nil
    ) {
        self.id = id
        self.title = title
        self.state = state
        self.message = message
        self.detail = detail
        self.fix = fix
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

/// `POST /api/setup/report`: the bug report with secrets removed, and the file it was saved
/// as. Nothing is sent anywhere.
public struct SetupReport: Codable, Sendable, Hashable {
    public var path: String
    public var text: String

    public init(path: String, text: String) {
        self.path = path
        self.text = text
    }
}
