import Foundation
import Testing

@testable import NestKit

/// A transcript page shows agent output and can ask for the device token, so what it may
/// ask, reach and open is checked in the app (D151).
@Suite struct WebPaneBridgeTests {
    private let base = URL(string: "http://127.0.0.1:8765")!

    @Test func onlyAllowedLinksLeaveThePage() {
        #expect(
            WebPaneBridge.parse(["kind": "openExternal", "url": "https://example.com"])
                == .openLink(URL(string: "https://example.com")!))
        for url in ["file:///etc/passwd", "ssh://x", "javascript:alert(1)", ""] {
            #expect(WebPaneBridge.parse(["kind": "openExternal", "url": url]) == nil)
        }
    }

    @Test func anythingElseIsRefused() {
        let bodies: [Any] = [
            "daemon", 3, ["kind": 1], ["kind": "nope"], ["kind": "copy"],
            ["kind": "message", "action": "delete", "event": 1],
            ["kind": "message", "action": "edit", "event": "1"],
            ["kind": "saveFile", "name": "a", "base64": "not base64"],
        ]
        for body in bodies {
            #expect(WebPaneBridge.parse(body) == nil)
        }
    }

    @Test func aSavedFileKeepsOnlyItsName() {
        let message = WebPaneBridge.parse([
            "kind": "saveFile", "name": "../../.zshrc", "base64": "aGk=",
        ])
        #expect(message == .saveFile(name: ".zshrc", data: Data("hi".utf8)))
    }

    @Test func thePageStaysOnTheDaemonAndLinksGoOutside() {
        let page = URL(string: "http://127.0.0.1:8765/desktop.html?view=transcript&chat=a")!
        #expect(WebPaneBridge.navigation(to: page, base: base, linkClick: false) == .stay)
        // A link in a message to the daemon's own address is still only a link.
        #expect(
            WebPaneBridge.navigation(to: page, base: base, linkClick: true) == .openOutside(page))
        let other = URL(string: "https://example.com/")!
        #expect(WebPaneBridge.navigation(to: other, base: base, linkClick: false) != .stay)
        let file = URL(string: "file:///Applications/Calculator.app")!
        #expect(WebPaneBridge.navigation(to: file, base: base, linkClick: true) == .cancel)
        #expect(WebPaneBridge.navigation(to: nil, base: base, linkClick: true) == .cancel)
    }

    @Test func onlyTheDaemonsOriginCounts() {
        func check(_ scheme: String, _ host: String, _ port: Int) -> Bool {
            WebPaneBridge.isDaemon(scheme: scheme, host: host, port: port, base: base)
        }
        #expect(check("http", "127.0.0.1", 8765))
        #expect(!check("https", "127.0.0.1", 8765))
        #expect(!check("http", "127.0.0.1", 8766))
        #expect(!check("http", "evil.example", 8765))
        let remote = URL(string: "https://mac.tail.ts.net")!
        #expect(
            WebPaneBridge.isDaemon(scheme: "https", host: "mac.tail.ts.net", port: 0, base: remote))
    }

    @Test func rulesBlockAllButTheDaemon() throws {
        func filters(_ url: URL) throws -> [(String, String)] {
            let data = Data(WebPaneBridge.contentRules(base: url).utf8)
            let rules = try #require(
                JSONSerialization.jsonObject(with: data) as? [[String: [String: String]]])
            return rules.map { ($0["trigger"]?["url-filter"] ?? "", $0["action"]?["type"] ?? "") }
        }
        let local = try filters(base)
        #expect(local.first?.0 == ".*")
        #expect(local.first?.1 == "block")
        #expect(
            local.dropFirst().map(\.0) == [
                #"^http://127\.0\.0\.1:8765/"#, #"^ws://127\.0\.0\.1:8765/"#, "^blob:", "^data:",
            ])
        let remote = try filters(URL(string: "https://mac.tail.ts.net/")!)
        #expect(remote.dropFirst().first?.0 == #"^https://mac\.tail\.ts\.net/"#)
        #expect(remote.dropFirst(2).first?.0 == #"^wss://mac\.tail\.ts\.net/"#)
    }

    @Test func eachDaemonKeepsOneRuleListAcrossLaunches() {
        let local = WebPaneBridge.rulesIdentifier(base: base)
        #expect(local == WebPaneBridge.rulesIdentifier(base: URL(string: "http://127.0.0.1:8765")!))
        #expect(local != WebPaneBridge.rulesIdentifier(base: URL(string: "http://127.0.0.1:8766")!))
    }

    @Test func theAddressCarriesNoToken() throws {
        func query(_ target: WebPaneBridge.Target) throws -> String? {
            try #require(WebPaneBridge.address(base: base, target: target)).query
        }
        #expect(try query(.pane("abc")) == "view=transcript&chat=abc")
        #expect(
            try query(.pane(ClaudeChat.panePrefix + "xyz")) == "view=transcript&claude=xyz")
        #expect(
            try query(.work(.pixie(session: "c1", pixieID: "p1")))
                == "view=transcript&session=c1&pixie=p1")
        #expect(
            try query(.work(.subagent(session: "c1", toolUseID: "t1")))
                == "view=transcript&session=c1&call=t1")
        #expect(
            try query(.work(.team(session: "c1", teamID: "t1", members: ["m"])))
                == "view=transcript&session=c1&team=t1")
    }

    @Test func aCommandsTextCannotBecomeCode() throws {
        let text = "x')); alert(1); ('"
        let row = BashStore.Row(id: "1", command: text, run: nil, failure: nil)
        let script = try #require(WebPaneBridge.script(.bash([row])))
        #expect(script.hasPrefix("window.dispatchEvent(new CustomEvent('nest-pane', { detail: {"))
        let json = try #require(
            script.dropFirst("window.dispatchEvent(new CustomEvent('nest-pane', { detail: ".count)
                .dropLast(" }))".count).data(using: .utf8))
        let object = try #require(JSONSerialization.jsonObject(with: json) as? [String: Any])
        let run = try #require((object["runs"] as? [[String: Any]])?.first)
        #expect(run["command"] as? String == text)
    }
}
