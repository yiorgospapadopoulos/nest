import Foundation
import Testing

@testable import NestKit

@MainActor
@Suite struct UpdatesTests {
    static let claude = EngineUpdate(
        id: "claude", name: "Claude Code", current: "2.1.317", new: "2.1.318")
    static let ready = EngineUpdates(state: .ready, engines: [claude], canUndo: true)

    let api = FakeAPI()
    let source = ManualEventSource()
    let model: AppModel
    var store: UpdatesStore { model.updates }

    init() {
        model = AppModel(api: api, events: source, preferences: MemoryStore())
    }

    private func calls(_ name: String) -> Int {
        api.calls.count { $0 == name }
    }

    /// Tells the live sync the socket connected and waits until it reloaded.
    private func connect() async throws {
        var connected = false
        model.live.onConnected = { connected = true }
        source.continuation.yield(.connected(resumed: false))
        try await waitFor { connected }
    }

    @Test func decodesTheDaemonsAnswer() {
        let status = Fixture.decode(
            EngineUpdates.self,
            json: """
                {"state": "none", "engines": [], "busy_chats": 2, "can_undo": true,
                 "notice": "Back on the old engines."}
                """)
        #expect(
            status == EngineUpdates(busyChats: 2, canUndo: true, notice: "Back on the old engines.")
        )
        let ready = Fixture.decode(
            EngineUpdates.self,
            json: """
                {"state": "ready", "busy_chats": 0, "can_undo": false, "notice": null,
                 "engines": [{"id": "claude", "name": "Claude Code", "current": "2.1.317",
                              "new": "2.1.318"}]}
                """)
        #expect(ready.state == .ready)
        #expect(ready.engines[0].change == "Claude Code 2.1.317 → 2.1.318")
    }

    @Test func aNewNestAloneIsAnUpdate() {
        let app = AppUpdate(version: "1.2.0", notes: "Faster.")
        let status = Fixture.decode(
            EngineUpdates.self,
            json: """
                {"state": "ready", "engines": [], "busy_chats": 0, "can_undo": false,
                 "notice": null, "app": {"version": "1.2.0", "notes": "Faster."},
                 "app_file": {"version": "1.1.0", "path": "/d/1.1.0/app-file"}}
                """)
        #expect(status.appFile == AppFile(version: "1.1.0", path: "/d/1.1.0/app-file"))
        model.live.route(
            Fixture.event(EventType.updatesChanged, Fixture.json(status), id: nil, session: nil))
        #expect(store.strip == .ready(app: app, engines: [], relaunching: false))
    }

    @Test func everyConnectFollowsTheDaemonsApp() async throws {
        let file = AppFile(version: "1.1.0", path: "/d/1.1.0/app-file")
        api.set { $0.updates = EngineUpdates(appFile: file) }
        var followed: [AppFile] = []
        store.followApp = { followed.append($0) }
        let run = Task { await model.live.run() }
        defer { run.cancel() }
        try await connect()
        #expect(followed == [file])
    }

    @Test func theEventReplacesTheState() async {
        model.live.route(
            Fixture.event(EventType.updatesChanged, Fixture.json(Self.ready), id: nil, session: nil)
        )
        #expect(store.status == Self.ready)
        #expect(store.strip == .ready(app: nil, engines: [Self.claude], relaunching: false))
    }

    @Test func aCheckRunsOnceAndEveryConnectReadsTheState() async throws {
        let run = Task { await model.live.run() }
        defer { run.cancel() }

        try await connect()
        #expect(calls("checkUpdates") == 1)
        #expect(calls("updates") == 1)

        api.set { $0.updates = Self.ready }
        try await connect()
        #expect(calls("checkUpdates") == 1)
        #expect(calls("updates") == 2)
        #expect(store.status == Self.ready)
    }

    @Test func aFailingCheckIsSilentAndNotRetried() async throws {
        api.fail("checkUpdates")
        api.set { $0.updates = Self.ready }
        await store.connected()
        await store.connected()
        #expect(store.status == Self.ready)
        #expect(calls("checkUpdates") == 1)
    }

    @Test func aNoticeWinsOverAReadyUpdateUntilDismissed() async throws {
        var both = Self.ready
        both.notice = "Back on the old engines."
        api.set { $0.updates = both }
        await store.load()
        #expect(store.strip == .notice("Back on the old engines."))

        try await store.dismissNotice()
        #expect(store.strip == .ready(app: nil, engines: [Self.claude], relaunching: false))
    }

    @Test(arguments: [EngineUpdates.Phase.idle, .checking, .preparing])
    func nothingShowsWhileNoUpdateIsReady(_ phase: EngineUpdates.Phase) async {
        api.set { $0.updates = EngineUpdates(state: phase) }
        await store.load()
        #expect(store.status?.state == phase)
        #expect(store.strip == nil)
    }

    @Test func relaunchGoesStraightOnWhenNoChatWouldStop() async throws {
        api.set { $0.updates = Self.ready }
        await store.load()
        try await store.start(.relaunch)
        #expect(store.asking == nil)
        #expect(calls("relaunchUpdate") == 1)
    }

    @Test func relaunchAsksWithTheBusyCountReadJustNow() async throws {
        api.set { $0.updates = Self.ready }
        await store.load()
        var busy = Self.ready
        busy.busyChats = 2
        api.set { $0.updates = busy }

        try await store.start(.relaunch)
        #expect(store.asking?.title == "Relaunch to update?")
        #expect(store.asking?.action == "Relaunch")
        #expect(store.asking?.about == "2 chats are mid-turn. They will stop and can be resumed.")
        #expect(calls("relaunchUpdate") == 0)

        store.cancel()
        #expect(store.asking == nil)
        #expect(store.restarting == nil)
        #expect(calls("relaunchUpdate") == 0)
    }

    @Test func relaunchFallsBackToTheStoredCount() async throws {
        var busy = Self.ready
        busy.busyChats = 1
        api.set { $0.updates = busy }
        await store.load()
        api.fail("updates")

        try await store.start(.relaunch)
        #expect(store.asking?.about == "1 chat is mid-turn. It will stop and can be resumed.")
    }

    @Test func undoAlwaysAsks() async throws {
        api.set { $0.updates = Self.ready }
        await store.load()
        #expect(store.offersUndo)

        try await store.start(.undo)
        #expect(store.asking?.title == "Undo update?")
        #expect(store.asking?.action == "Undo update")
        #expect(store.asking?.about == "Nest relaunches on the engines from before.")
        #expect(calls("undoUpdate") == 0)

        try await store.run(.undo)
        #expect(calls("undoUpdate") == 1)
        #expect(store.asking == nil)
        // Undoing shows no strip, and the row stays until the daemon is back.
        #expect(store.strip == nil)
    }

    @Test func relaunchingLastsUntilTheSocketConnectsAgain() async throws {
        api.set { $0.updates = Self.ready }
        await store.load()

        try await store.run(.relaunch)
        model.live.route(
            Fixture.event(
                EventType.updatesChanged, Fixture.json(EngineUpdates()), id: nil, session: nil))
        #expect(store.status?.state == .idle)
        #expect(store.strip == .ready(app: nil, engines: [], relaunching: true))

        await store.connected()
        #expect(store.restarting == nil)
        #expect(store.strip == nil)
    }

    @Test func theAppReopensOnlyOnceTheDaemonAccepted() async throws {
        var reopened = 0
        store.reopen = { reopened += 1 }
        api.set { $0.updates = Self.ready }
        await store.load()
        api.fail("relaunchUpdate", with: APIError.conflict("No update is ready"))

        await #expect(throws: APIError.self) { try await store.run(.relaunch) }
        #expect(reopened == 0)

        api.set { $0.failures["relaunchUpdate"] = nil }
        try await store.run(.relaunch)
        #expect(reopened == 1)
        #expect(store.strip == .ready(app: nil, engines: [Self.claude], relaunching: true))

        try await store.run(.undo)
        #expect(reopened == 2)
    }

    @Test func withoutAReopenTheAppStaysUntilTheDaemonIsBack() async throws {
        api.set { $0.updates = Self.ready }
        await store.load()

        try await store.run(.undo)
        #expect(store.restarting == .undo)

        await store.connected()
        #expect(store.restarting == nil)
        #expect(store.strip == .ready(app: nil, engines: [Self.claude], relaunching: false))
    }

    @Test func hidingLastsThroughReconnectsAndOnlyForThisStore() async throws {
        api.set { $0.updates = Self.ready }
        await store.load()

        store.hideStrip()
        #expect(store.strip == nil)
        #expect(store.ready == ReadyUpdate(app: nil, engines: [Self.claude], relaunching: false))

        await store.connected()
        model.live.route(
            Fixture.event(EventType.updatesChanged, Fixture.json(Self.ready), id: nil, session: nil)
        )
        #expect(store.strip == nil)
        #expect(calls("dismissUpdateNotice") == 0)

        let fresh = UpdatesStore(api: api)
        await fresh.load()
        #expect(fresh.strip == .ready(app: nil, engines: [Self.claude], relaunching: false))
    }

    @Test func aHiddenStripStillShowsANotice() async {
        var notice = Self.ready
        notice.notice = "Back on the old engines."
        api.set { $0.updates = notice }
        await store.load()

        store.hideStrip()
        #expect(store.strip == .notice("Back on the old engines."))
        #expect(store.ready == ReadyUpdate(app: nil, engines: [Self.claude], relaunching: false))
    }

    @Test func aRefusedRelaunchComesBackToTheStrip() async throws {
        api.set { $0.updates = Self.ready }
        await store.load()
        api.fail("relaunchUpdate", with: APIError.conflict("No update is ready"))
        api.set { $0.updates = EngineUpdates() }

        await #expect(throws: APIError.self) { try await store.run(.relaunch) }
        #expect(store.restarting == nil)
        #expect(store.strip == nil)
    }
}
