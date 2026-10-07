import Foundation

/// A failed API call, typed by the daemon's status code, with its `detail` message.
public enum APIError: Error, Sendable, Equatable {
    case unauthorized(String)
    case notFound(String)
    /// A dirty checkout lists its changed files.
    case conflict(String, files: [String])
    /// The chat is open in Claude Code right now; it has to be closed there first.
    case openInClaudeCode(String)
    case invalidInput(String)
    case payloadTooLarge(String)
    case rateLimited(String, retryAfter: Int?)
    /// A local app (VS Code) is not installed.
    case appNotInstalled(String)
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
        case .unauthorized(let detail), .notFound(let detail), .conflict(let detail, _),
            .openInClaudeCode(let detail), .invalidInput(let detail), .payloadTooLarge(let detail),
            .rateLimited(let detail, _), .appNotInstalled(let detail),
            .gitFailed(let detail, _, _), .badGateway(let detail), .server(_, let detail),
            .transport(let detail), .decoding(let detail):
            detail
        }
    }

    /// Maps an error response; FastAPI validation errors carry a list of messages.
    static func from(_ response: HTTPResponse) -> APIError {
        let body = (try? HarnessJSON.decoder.decode(JSONValue.self, from: response.body)) ?? .null
        let fallback = HTTPURLResponse.localizedString(forStatusCode: response.status)
        let detail = detailText(body["detail"]) ?? fallback
        switch response.status {
        case 401: return .unauthorized(detail)
        case 404: return .notFound(detail)
        case 409 where body["code"]?.stringValue == "open_in_claude_code":
            return .openInClaudeCode(detail)
        case 409:
            let files = body["files"]?.arrayValue?.compactMap(\.stringValue) ?? []
            return .conflict(detail, files: files)
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
