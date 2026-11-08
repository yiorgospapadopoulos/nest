import Foundation

/// The error codes of the helper protocol (B150 design, "Helper protocol").
public enum ErrorCode: String, Sendable, Equatable {
    case badRequest = "bad_request"
    case noPermission = "no_permission"
    case notFound = "not_found"
    case stale
    case secureField = "secure_field"
    case notFront = "not_front"
    case failed
}

/// A failed request, as the reply's `error`.
public struct HelperError: Error, Sendable, Equatable {
    public let code: ErrorCode
    public let message: String

    public init(_ code: ErrorCode, _ message: String) {
        self.code = code
        self.message = message
    }
}

/// One request line: `{"id": 1, "op": "...", "args": {...}}`.
public struct Request: Sendable, Equatable {
    public let id: Int
    public let op: String
    public let args: [String: JSONValue]

    public init(id: Int, op: String, args: [String: JSONValue] = [:]) {
        self.id = id
        self.op = op
        self.args = args
    }
}

/// A line that is not a usable request. `id` is the request's id when it could be read, so
/// the reply still answers it; otherwise the reply's id is null.
public struct RequestError: Error, Sendable, Equatable {
    public let id: Int?
    public let error: HelperError
}

/// One reply line.
public enum Reply: Sendable, Equatable {
    case success(id: Int?, result: [String: JSONValue])
    case failure(id: Int?, error: HelperError)

    /// The reply as one JSON line, ending in a newline.
    public func line() -> Data {
        let object: JSONValue
        switch self {
        case .success(let id, let result):
            object = ["id": id.map(JSONValue.int) ?? .null, "ok": true, "result": .object(result)]
        case .failure(let id, let error):
            object = [
                "id": id.map(JSONValue.int) ?? .null, "ok": false,
                "error": ["code": .string(error.code.rawValue), "message": .string(error.message)],
            ]
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        // Encoding a JSONValue cannot fail: it holds only JSON values.
        var data = (try? encoder.encode(object)) ?? Data()
        data.append(0x0A)
        return data
    }
}

/// Reads one request line.
public func decodeRequest(_ line: Data) -> Result<Request, RequestError> {
    guard case .object(let fields)? = try? JSONDecoder().decode(JSONValue.self, from: line) else {
        return .failure(RequestError(id: nil, error: HelperError(.badRequest, "not a JSON object")))
    }
    guard case .int(let id)? = fields["id"] else {
        return .failure(
            RequestError(id: nil, error: HelperError(.badRequest, "id must be an integer")))
    }
    guard case .string(let op)? = fields["op"], !op.isEmpty else {
        return .failure(RequestError(id: id, error: HelperError(.badRequest, "op is missing")))
    }
    switch fields["args"] {
    case nil, .null:
        return .success(Request(id: id, op: op))
    case .object(let args):
        return .success(Request(id: id, op: op, args: args))
    default:
        return .failure(
            RequestError(id: id, error: HelperError(.badRequest, "args must be an object")))
    }
}
