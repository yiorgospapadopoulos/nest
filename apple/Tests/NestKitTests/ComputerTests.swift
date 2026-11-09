import Foundation
import Testing

@testable import NestKit

/// Computer use (B150): what the Mac app reads from the daemon and keeps per chat.
@MainActor
@Suite struct ComputerTests {
    let api = FakeAPI()
    let store: ComputerStore

    init() {
        store = ComputerStore(api: api)
    }

    // MARK: Decoding

    @Test func aSessionFromAnOlderDaemonHasComputerUseOff() {
        let session = Fixture.decode(Session.self, json: Fixture.json(Fixture.session()))
        #expect(session.allowedComputerTargets.isEmpty)
    }

    @Test func aSessionDecodesItsTargets() {
        let json =
            String(Fixture.json(Fixture.session()).dropLast())
            + #","computer_targets": ["mac:com.apple.TextEdit", "browser"]}"#
        let session = Fixture.decode(Session.self, json: json)
        #expect(session.allowedComputerTargets == ["mac:com.apple.TextEdit", "browser"])
    }

    @Test func settingsAndStatusDecodeAsTheDaemonSendsThem() {
        let settings = Fixture.decode(
            ComputerUseSettings.self,
            json: #"{"enabled": true, "pixies": false}"#)
        #expect(settings == ComputerUseSettings(enabled: true))

        let status = Fixture.decode(
            ComputerStatus.self,
            json: #"""
                {"enabled": true, "accessibility": true, "screen_recording": false, "kinds": [
                 {"kind": "mac", "ready": true, "reason": null, "link": null},
                 {"kind": "android", "ready": false, "reason": "Android Studio is not installed.",
                  "link": "https://developer.android.com/studio"},
                 {"kind": "tv", "ready": true}]}
                """#)
        #expect(ComputerPermission.accessibility.granted(in: status) == true)
        #expect(ComputerPermission.screenRecording.granted(in: status) == false)
        #expect(status.kind(.android)?.reason == "Android Studio is not installed.")
        #expect(status.kind(.android)?.link == "https://developer.android.com/studio")
        // A kind added later does not break the page.
        #expect(status.kinds.last?.kind == .unknown)

        // Off a Mac the permissions are missing.
        let linux = Fixture.decode(
            ComputerStatus.self, json: #"{"enabled": false, "kinds": []}"#)
        #expect(linux.accessibility == nil)
        #expect(linux.screenRecording == nil)
    }

    /// A computer card is answered for its chat only: never Always allow.
    @Test func aComputerCardDecodesWhatItAsks() throws {
        let use = Fixture.decode(
            PermissionRequest.self,
            json: #"""
                {"tool": "computer_use", "input": {"target": "mac:com.apple.TextEdit"},
                 "title": "Let this chat use TextEdit?", "reason": null, "always_rule": null,
                 "always": false,
                 "computer": {"target": "mac:com.apple.TextEdit", "name": "TextEdit", "kind": "use"}}
                """#)
        let ask = try #require(use.computer)
        #expect(ask.name == "TextEdit")
        #expect(!use.always)
    }

    // MARK: What a chat holds

    @Test func theStateShowsWhatTheChatHoldsUntilItLetsGo() {
        store.apply(
            Fixture.event(
                EventType.computerState,
                #"{"targets": [{"key": "mac:com.apple.TextEdit", "name": "TextEdit"}]}"#))
        let textEdit = ComputerTarget(key: "mac:com.apple.TextEdit", name: "TextEdit")
        #expect(store.targets(of: "s1") == [textEdit])
        #expect(store.targets(of: "s2").isEmpty)

        store.apply(Fixture.event(EventType.computerState, #"{"targets": []}"#, id: 2))
        #expect(store.targets(of: "s1").isEmpty)
        #expect(store.frame(of: "s1") == nil)
    }

    /// The glow follows every app in use, on its window's screen, until the last lets go.
    @Test func theGlowFollowsEachAppInUse() {
        #expect(store.inUse.isEmpty)
        store.apply(
            Fixture.event(
                EventType.computerState,
                #"""
                {"targets": [{"key": "mac:com.apple.TextEdit", "name": "TextEdit",
                 "frame": {"x": 100, "y": 80, "width": 586, "height": 488}}]}
                """#))
        #expect(
            store.inUse.map(\.frame)
                == [ComputerTarget.WindowFrame(x: 100, y: 80, width: 586, height: 488)])

        store.apply(Fixture.event(EventType.computerState, #"{"targets": []}"#, id: 2))
        #expect(store.inUse.isEmpty)
    }

    @Test func eachNewFrameIsReadOnce() async {
        let first = Data("png 1".utf8)
        api.set { $0.computerFrames["s1"] = first }
        let frame =
            #"{"target": "mac:com.apple.TextEdit", "label": "TextEdit: Notes.rtf", "seq": 1}"#
        store.apply(Fixture.event(EventType.computerFrame, frame, id: nil))
        // A frame seen before the state, as after a reconnect, still shows the preview.
        #expect(store.targets(of: "s1").map(\.name) == ["TextEdit"])

        await store.loadFrame(of: "s1")
        await store.loadFrame(of: "s1")
        #expect(store.image(of: "s1") == first)
        #expect(api.calls == ["computerFrame s1"])

        let second = Data("png 2".utf8)
        api.set { $0.computerFrames["s1"] = second }
        store.apply(
            Fixture.event(
                EventType.computerFrame,
                #"{"target": "mac:com.apple.TextEdit", "label": "TextEdit: Notes.rtf", "seq": 2}"#,
                id: nil))
        await store.loadFrame(of: "s1")
        #expect(store.image(of: "s1") == second)
        #expect(api.calls == ["computerFrame s1", "computerFrame s1"])
    }

    @Test func aRefusedSettingsChangeIsUndone() async {
        api.fail("updateComputerSettings")
        await #expect(throws: (any Error).self) {
            try await store.update { $0.enabled = true }
        }
        #expect(store.settings?.enabled == false)
    }
}
