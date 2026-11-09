import Foundation
import NestComputerCore
import Testing

@Suite struct ProtocolTests {
    private func command(_ op: String, _ args: [String: JSONValue] = [:]) throws(HelperError)
        -> Command
    {
        try Command(Request(id: 1, op: op, args: args))
    }

    private func error(_ op: String, _ args: [String: JSONValue] = [:]) -> HelperError? {
        do {
            _ = try command(op, args)
            return nil
        } catch {
            return error
        }
    }

    private func object(_ data: Data) throws -> [String: Any] {
        try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    @Test func aRequestLineIsRead() throws {
        let line = Data(#"{"id": 7, "op": "tree", "args": {"window": "w3", "max_nodes": 50}}"#.utf8)
        let request = try decodeRequest(line).get()
        #expect(request == Request(id: 7, op: "tree", args: ["window": "w3", "max_nodes": 50]))
        #expect(try Command(request) == .tree(window: "w3", maxNodes: 50, maxDepth: 30))
    }

    @Test func unreadableLinesAreBadRequests() {
        func failure(_ text: String) -> RequestError? {
            if case .failure(let error) = decodeRequest(Data(text.utf8)) { return error }
            return nil
        }
        #expect(failure("not json")?.id == nil)
        #expect(failure(#"{"op": "apps"}"#)?.id == nil)
        // The id is kept when it can be read, so the reply still answers the request.
        #expect(failure(#"{"id": 4}"#)?.id == 4)
        #expect(failure(#"{"id": 4}"#)?.error.code == .badRequest)
        #expect(failure(#"{"id": 5, "op": "apps", "args": [1]}"#)?.error.code == .badRequest)
    }

    @Test func repliesAreOneJSONLine() throws {
        let success = Reply.success(id: 3, result: ["pid": 42, "path": "a/b\nc"]).line()
        #expect(success.last == 0x0A)
        #expect(success.dropLast().contains(0x0A) == false)
        let ok = try object(success)
        #expect(ok["id"] as? Int == 3)
        #expect(ok["ok"] as? Bool == true)
        #expect((ok["result"] as? [String: Any])?["path"] as? String == "a/b\nc")

        let failure = try object(Reply.failure(id: nil, error: HelperError(.stale, "gone")).line())
        #expect(failure["id"] is NSNull)
        #expect(failure["ok"] as? Bool == false)
        let error = try #require(failure["error"] as? [String: Any])
        #expect(error["code"] as? String == "stale")
        #expect(error["message"] as? String == "gone")
    }

    @Test func everyErrorCodeHasItsWireName() {
        let names = [
            ErrorCode.badRequest, .noPermission, .notFound, .stale, .secureField, .notFront,
            .failed,
        ].map(\.rawValue)
        #expect(
            names == [
                "bad_request", "no_permission", "not_found", "stale", "secure_field", "not_front",
                "failed",
            ])
    }

    @Test func unknownOpsAndBadArgumentsAreRefused() {
        #expect(error("draw")?.code == .badRequest)
        #expect(error("tree", ["window": "e3"])?.code == .badRequest)
        #expect(error("tree", ["window": "w3", "max_nodes": 0])?.code == .badRequest)
        #expect(error("press", ["element": "e1", "action": "rm -rf"])?.code == .badRequest)
        #expect(error("type", ["text": "hi"])?.code == .badRequest)
        #expect(error("type", ["pid": -1, "text": "hi"])?.code == .badRequest)
        #expect(error("key", ["pid": 9, "key": "f13"])?.code == .badRequest)
        #expect(error("key", ["pid": 9, "key": "a", "modifiers": ["super"]])?.code == .badRequest)
        #expect(error("scroll", ["direction": "down"])?.code == .badRequest)
        #expect(error("menu", ["pid": 9, "path": []])?.code == .badRequest)
        #expect(error("ask_permission", ["name": "camera"])?.code == .badRequest)
    }

    @Test func argumentsGetTheirDefaults() throws {
        #expect(
            try command("press", ["element": "e12"]) == .press(element: "e12", action: "AXPress"))
        #expect(
            try command("scroll", ["pid": 9, "direction": "up"])
                == .scroll(target: .pid(9), direction: .up, amount: 3))
        #expect(
            try command("key", ["pid": 9, "key": "Return", "modifiers": ["cmd", "shift"]])
                == .key(pid: 9, code: 36, modifiers: [.cmd, .shift]))
        #expect(
            try command("set_value", ["element": "e2", "text": ""])
                == .setValue(element: "e2", text: ""))
        #expect(try command("front", ["pid": 9]) == .front(pid: 9, window: nil))
    }

    @Test func onlyHelloPermissionsAndLaunchSkipAccessibility() throws {
        #expect(try command("hello").needsAccessibility == false)
        #expect(
            try command("launch", ["bundle_id": "com.apple.TextEdit"]).needsAccessibility == false)
        #expect(try command("apps").needsAccessibility)
        #expect(try command("screenshot", ["window": "w1"]).needsAccessibility)
    }
}
