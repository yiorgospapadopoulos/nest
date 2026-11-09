import Foundation
import Testing

@testable import NestKit

/// Terminal agents (B151): Settings switches outside clients on at a level, and `nest open`
/// links open a chat.
@MainActor
@Suite struct TerminalAgentsTests {
    let api = FakeAPI()
    let store: TerminalAgentsStore

    init() {
        store = TerminalAgentsStore(api: api)
        api.set {
            $0.outsideClients = [
                OutsideClient(kind: .claudeCode, label: "Claude Code"),
                OutsideClient(kind: .shell, label: "nest command", command: ["/x y/nest"]),
            ]
        }
    }

    @Test func aClientDecodesAsTheDaemonSendsIt() {
        let client = Fixture.decode(
            OutsideClient.self,
            json: #"""
                {"kind": "other", "label": "Other MCP apps", "on": true, "access": "message",
                 "turned_on_at": "2026-11-09T01:00:00Z", "last_seen_at": null,
                 "command": ["/Users/me/my apps/nest", "mcp", "--client", "other"]}
                """#)
        #expect(client.access == .message)
        #expect(client.commandLine == #""/Users/me/my apps/nest" mcp --client other"#)
    }

    @Test func switchingAClientOnShowsItAsTheDaemonReportsIt() async throws {
        try await store.load()

        try await store.set(.claudeCode, .read)
        try await store.set(.claudeCode, .full)

        #expect(store.clients?.first?.on == true)
        #expect(store.clients?.first?.access == .full)
        #expect(
            api.calls.suffix(2) == [
                "turnOnOutsideClient claude_code read", "turnOnOutsideClient claude_code full",
            ])
    }

    @Test func aRefusedClientStaysOff() async throws {
        try await store.load()
        api.set {
            $0.failNext["turnOnOutsideClient"] = APIError.invalidInput("Codex was not found.")
        }

        await #expect(throws: APIError.self) { try await store.set(.claudeCode, .read) }

        #expect(store.clients?.first?.on == false)
        #expect(store.changing == nil)
    }

    @Test func aNestLinkNamesTheChatAndItsProject() throws {
        let link = try #require(NestLink(URL(string: "nest://chat/1b624978acee?project=my%20app")!))
        #expect(link.chat == "1b624978acee")
        #expect(link.project == "my app")
        #expect(NestLink(URL(string: "nest://chat/1b62?project=")!) == nil)
        #expect(NestLink(URL(string: "nest://pixie/1b62?project=a")!) == nil)
        #expect(NestLink(URL(string: "https://chat/1b62?project=a")!) == nil)
        #expect(NestLink(URL(string: "nest://chat/..%2F..?project=a")!) == nil)
    }
}
