import Foundation

/// A failed API call, typed by the daemon's status code, with its `detail` message.
public enum APIError: Error, Sendable, Equatable {
    case unauthorized(String)
    case notFound(String)
    /// Any other 409, such as a busy or closed chat.
    case conflict(String)
    /// The chat is open in Claude Code right now; it has to be closed there first.
    case openInClaudeCode(String)
    /// Claude already read the pending message, so it can no longer be removed (B59).
    case messageTaken(String)
    /// A pixie file changed since it was read; carries the current text and hash.
    case staleFile(text: String, hash: String)
    case invalidInput(String)
    case payloadTooLarge(String)
    case rateLimited(String, retryAfter: Int?)
    /// A local app (VS Code) is not installed.
    case appNotInstalled(String)
    /// Approve was refused before publishing anything (409 with a known code); a push
    /// address that needs confirming comes with where origin pushes now.
    case approveRefused(String, reason: ApproveRefusal, remote: PushRemote? = nil)
    /// A git or gh step of the approve flow failed; the review stays pending.
    case gitFailed(String, step: String, stderr: String)
    case badGateway(String)
    case server(status: Int, detail: String)
    /// The daemon could not be reached.
    case transport(String)
    /// The response was not what the daemon's API promises.
    case decoding(String)

    public var message: String {
        switch self {
        case .staleFile:
            "The file changed since you opened it."
        case .unauthorized(let detail), .notFound(let detail), .conflict(let detail),
            .openInClaudeCode(let detail), .messageTaken(let detail), .invalidInput(let detail), .payloadTooLarge(let detail),
            .rateLimited(let detail, _), .appNotInstalled(let detail),
            .gitFailed(let detail, _, _), .badGateway(let detail), .server(_, let detail),
            .transport(let detail), .decoding(let detail), .approveRefused(let detail, _, _):
            detail
        }
    }

    /// A 409: the chat changed since the app last read it.
    public var isConflict: Bool {
        switch self {
        case .conflict, .openInClaudeCode, .messageTaken, .approveRefused: true
        default: false
        }
    }

    /// Where origin pushes now, when approving was refused until the user confirms it.
    public var pushRemote: PushRemote? {
        if case .approveRefused(_, _, let remote) = self { remote } else { nil }
    }

    /// Maps an error response; FastAPI validation errors carry a list of messages.
    static func from(_ response: HTTPResponse) -> APIError {
        let body = (try? NestJSON.decoder.decode(JSONValue.self, from: response.body)) ?? .null
        let fallback = HTTPURLResponse.localizedString(forStatusCode: response.status)
        let detail = detailText(body["detail"]) ?? fallback
        switch response.status {
        case 401: return .unauthorized(detail)
        case 404: return .notFound(detail)
        case 409 where body["code"]?.stringValue == "open_in_claude_code":
            return .openInClaudeCode(detail)
        case 409 where body["code"]?.stringValue == "message_taken":
            return .messageTaken(detail)
        case 409:
            if body["code"]?.stringValue == "stale_file", let text = body["text"]?.stringValue,
                let hash = body["hash"]?.stringValue
            {
                return .staleFile(text: text, hash: hash)
            }
            if let refusal = body["code"]?.stringValue.flatMap(ApproveRefusal.init(rawValue:)) {
                return .approveRefused(detail, reason: refusal, remote: PushRemote(body, refusal))
            }
            return .conflict(detail)
        case 413: return .payloadTooLarge(detail)
        case 400, 422: return .invalidInput(detail)
        case 424: return .appNotInstalled(detail)
        case 429:
            let header = response.headers["retry-after"].flatMap { Int($0) }
            let field = body["retry_after"]?.numberValue.map { Int($0) }
            return .rateLimited(detail, retryAfter: header ?? field)
        case 502:
            if let step = body["step"]?.stringValue {
                return .gitFailed(detail, step: step, stderr: body["stderr"]?.stringValue ?? "")
            }
            return .badGateway(detail)
        default: return .server(status: response.status, detail: detail)
        }
    }

    private static func detailText(_ detail: JSONValue?) -> String? {
        if let text = detail?.stringValue {
            return text
        }
        let messages = detail?.arrayValue?.compactMap { $0["msg"]?.stringValue } ?? []
        return messages.isEmpty ? nil : messages.joined(separator: "; ")
    }
}

/// Why the daemon refused to publish a review; its `detail` says it in words.
public enum ApproveRefusal: String, Sendable {
    /// HEAD is no longer the commit or branch the review showed.
    case headChanged = "head_changed"
    /// The chat's background tasks still run.
    case backgroundRunning = "background_running"
    /// A git repository inside the work cannot be committed.
    case nestedRepository = "nested_repository"
    case unsafeBranch = "unsafe_branch"
    case unsafeRepoConfig = "unsafe_repo_config"
    case remoteNotConfirmed = "remote_not_confirmed"
    case remoteChanged = "remote_changed"
    /// A changed file is marked assume-unchanged or skip-worktree; the detail names them.
    case indexFlags = "index_flags"
    /// The repository uses git-lfs, which approving cannot publish.
    case lfsUnsupported = "lfs_unsupported"
    /// The changes differ from the review the user saw.
    case reviewChanged = "review_changed"

    /// What to do, beyond the daemon's own words.
    public var hint: String? {
        switch self {
        case .headChanged: "The branch moved since you looked. Check the changes again."
        case .reviewChanged: "The changes were read again. Check them before approving."
        default: nil
        }
    }
}

/// Where origin pushes now, from a `remote_not_confirmed` or `remote_changed` refusal
/// (D050): the user can approve again with that address confirmed (I-008).
public struct PushRemote: Sendable, Hashable {
    /// Origin's push URLs now; none when origin is gone.
    public var urls: [String]
    /// The address Nest recorded before, for `remote_changed`.
    public var confirmedURL: String?

    public init(urls: [String], confirmedURL: String? = nil) {
        self.urls = urls
        self.confirmedURL = confirmedURL
    }

    init?(_ body: JSONValue, _ refusal: ApproveRefusal) {
        guard refusal == .remoteNotConfirmed || refusal == .remoteChanged else { return nil }
        urls = body["remote_urls"]?.arrayValue?.compactMap(\.stringValue) ?? []
        confirmedURL = body["confirmed_url"]?.stringValue
    }

    /// The one address "Push there" confirms; nil when origin pushes to several or none,
    /// which only the repository's own settings can sort out.
    public var target: String? {
        urls.count == 1 ? urls[0] : nil
    }

    /// Where origin pushes now, in words.
    public var summary: String {
        switch urls.count {
        case 0: "origin has no push address"
        case 1: confirmedURL == nil ? "origin pushes to" : "origin now pushes to"
        default: "origin pushes to several addresses; fix the remote before pushing"
        }
    }
}
