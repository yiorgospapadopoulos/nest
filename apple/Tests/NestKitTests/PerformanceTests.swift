import Foundation
import Testing

@testable import NestKit

/// B115: Settings > Performance, the daemon's results and runs and the Mac app's own
/// measurement.
@MainActor
@Suite struct PerformanceTests {
    static var view: PerfView { Fixture.decode(PerfView.self, "perf") }

    func store(_ view: PerfView = Self.view) -> (PerformanceStore, FakeAPI) {
        let api = FakeAPI()
        api.set { $0.perf = view }
        return (PerformanceStore(api: api, pause: { _ in }), api)
    }

    @Test func decodesTheContractsBody() throws {
        let view = Self.view
        #expect(view.running == nil)
        #expect(view.lastRun?.durationMs == 102_000)
        #expect(view.cards.count == 4)
        #expect(view.runs == 12)
        let context = view.cards[0]
        #expect(context.unit == .tokens)
        #expect(context.change == PerfChangeMark(text: "▲ 1.2k", direction: "up", tone: .worse))
        #expect(context.parts?.map(\.text) == ["23k", "6.2k"])
        // Keys the daemon may leave out decode as nil.
        #expect(view.cards[2].sub == nil && view.cards[2].parts == nil)
        let load = try #require(view.section("load"))
        #expect(load.runner == .daemon && !load.advanced && !load.live)
        #expect(load.ranAt != nil)
        #expect(load.note?.hasPrefix("Times on the daemon") == true)
        #expect(load.metrics[1].sub == "2.1 MB")
        #expect(load.metrics[1].previousText == "2.4 s")
        #expect(load.metrics[2].previous == nil && load.metrics[2].change == nil)
        let context2 = try #require(view.section("context"))
        #expect(context2.live && context2.ranAt == nil)
        #expect(context2.error == "Claude is not signed in")
        let activity = try #require(view.section("activity"))
        #expect(activity.series?.points.map(\.value) == [212, 106])
        let mac = try #require(view.section("mac"))
        #expect(mac.runner == .mac && mac.advanced)
        #expect(mac.metrics[0].value == nil && mac.metrics[0].text == "-")
        #expect(
            view.changes == [PerfChange(text: "Context +1.2k: new MCP server linear", tone: .worse)]
        )
        // A running run, and values a newer daemon may add, decode too.
        let running = Fixture.decode(
            PerfView.self,
            json: """
                {"running": {"id": "r", "sections": ["load"], "started_at": "2026-11-02T10:00:00Z"},
                 "last_run": null, "cards": [], "changes": [], "runs": 0,
                 "sections": [{"id": "x", "title": "X", "advanced": false, "runner": "phone",
                   "live": false, "ran_at": null, "error": null, "note": null, "series": null,
                   "metrics": [{"id": "m", "label": "M", "value": 1, "unit": "watts",
                     "text": "1", "change": {"text": "?", "direction": "up", "tone": "odd"}}]}]}
                """)
        #expect(running.running?.sections == ["load"])
        #expect(running.sections[0].runner == .unknown)
        #expect(running.sections[0].metrics[0].unit == .unknown)
        #expect(running.sections[0].metrics[0].change?.tone == .unknown)
    }

    /// Bars scale against the largest value or previous of the same unit in the section,
    /// so units never share a scale and nothing goes past full.
    @Test func barsScaleWithinAUnit() {
        func metric(_ id: String, _ value: Double?, _ previous: Double?, _ unit: PerfUnit)
            -> PerfMetric
        {
            PerfMetric(id: id, label: id, value: value, unit: unit, text: "", previous: previous)
        }
        let bars = PerfBars.scale([
            metric("open", 420, 480, .ms),
            metric("biggest", 1_800, 2_400, .ms),
            metric("size", 2_000_000, nil, .bytes),
            metric("empty", nil, nil, .ms),
            metric("zero", 0, 0, .count),
            metric("share", 13, nil, .percent),
        ])
        #expect(bars["open"] == PerfBar(previous: 0.2, current: 0.175))
        #expect(bars["biggest"] == PerfBar(previous: 1, current: 0.75))
        #expect(bars["size"] == PerfBar(previous: nil, current: 1))
        #expect(bars["empty"] == PerfBar(previous: nil, current: nil))
        #expect(bars["zero"] == PerfBar(previous: 0, current: 0))
        // A share is drawn against the whole, even when it is the only one.
        #expect(bars["share"] == PerfBar(previous: nil, current: 0.13))
        let days = PerfBars.days(
            PerfSeries(
                label: "", points: [.init(day: "a", value: 50), .init(day: "b", value: 200)]))
        #expect(days == [0.25, 1])
    }

    @Test func statesFollowTheResults() async {
        let never = PerfView(
            cards: [], sections: [PerfSection(id: "load", title: "Load speed")], runs: 0)
        let (store, api) = store(never)
        #expect(store.state == .loading)
        await store.load()
        #expect(store.state == .neverRun)
        let load = store.view!.sections[0]
        #expect(store.canRun(load))
        await store.run(load)
        #expect(store.state == .running)
        #expect(store.isRunning(load))
        #expect(!store.canRun(load))
        // The run finishes elsewhere; its event reads the results again.
        api.set { $0.perf = Self.view }
        store.apply(Fixture.event(EventType.perfRun, "{}", id: nil, session: nil))
        await api.untilCalls { $0.filter { $0 == "perf" }.count == 2 }
        await waitUntil { store.state == .finished }
        #expect(store.state == .finished)
        #expect(api.calls == ["perf", "runPerf load", "perf"])
    }

    @Test func aFailedCallSaysSoAndKeepsTheResults() async {
        let (store, api) = store()
        await store.load()
        api.fail("runPerf", with: APIError.conflict("A run is already running"))
        await store.runAll()
        #expect(store.failure == "Could not start the run: A run is already running")
        #expect(store.state == .finished)
        api.fail("perf")
        await store.load()
        #expect(store.failure?.hasPrefix("Could not read the results") == true)
        #expect(store.view == Self.view)
    }

    /// The section's own error shows on it; the page as a whole is still finished.
    @Test func aSectionErrorStaysOnItsSection() async {
        let (store, _) = store()
        await store.load()
        #expect(store.state == .finished)
        #expect(store.view?.section("context")?.error == "Claude is not signed in")
        #expect(store.mainSections.map(\.id) == ["load", "context", "activity"])
        #expect(store.advancedSections.map(\.id) == ["mac"])
    }

    /// Run all starts the daemon's sections, then measures the Mac app and records it;
    /// Run on the Mac section measures only; Clear old runs clears.
    @Test func runsAndClearCallTheRightRoutes() async {
        let (store, api) = store()
        var measured = 0
        store.measureMac = {
            measured += 1
            return [
                "layout_ms": 812, "scroll_ms": 2_400, "memory_before": 1,
                "memory_after": 2,
            ]
        }
        await store.load()
        await store.runAll()
        #expect(measured == 1)
        #expect(!store.measuringMac)
        await store.run(store.view!.section("mac")!)
        #expect(measured == 2)
        await store.clearOldRuns()
        let record = "recordPerf mac layout_ms,memory_after,memory_before,scroll_ms"
        #expect(api.calls == ["perf", "runPerf", record, record, "clearPerf"])
    }

    /// A Mac result that arrives while a daemon run holds the results waits for it.
    @Test func aMacResultWaitsForTheDaemonRun() async {
        let (store, api) = store()
        api.set { $0.failNext["recordPerf"] = APIError.conflict("A run is running") }
        store.measureMac = { ["layout_ms": 5] }
        await store.load()
        await store.runMac()
        #expect(store.failure == nil)
        #expect(
            api.calls == ["perf", "recordPerf mac layout_ms", "perf", "recordPerf mac layout_ms"])
        // A measurement that fails says so and records nothing.
        store.measureMac = { throw APIError.transport("gone") }
        await store.runMac()
        #expect(store.failure == "Could not measure the Mac app: gone")
        #expect(api.calls.count == 4)
    }

    /// The daemon's biggest chat when it names one, else the listed chat with the most
    /// context used.
    @Test func theMacMeasurementOpensTheBiggestChat() {
        var small = Fixture.sessions[0]
        small.id = "small"
        small.context = SessionContext(percent: 5, used: 10_000, limit: 200_000)
        var big = small
        big.id = "big"
        big.context = SessionContext(percent: 60, used: 120_000, limit: 200_000)
        #expect(PerformanceStore.biggestChat(in: Self.view, sessions: [small, big]) == "big")
        #expect(PerformanceStore.biggestChat(in: nil, sessions: []) == nil)
        var named = Self.view
        named.sections[0].metrics[1].chatID = "named"
        #expect(PerformanceStore.biggestChat(in: named, sessions: [small, big]) == "named")
    }

    private func waitUntil(_ condition: @MainActor () -> Bool) async {
        for _ in 0..<200 where !condition() {
            await Task.yield()
            try? await Task.sleep(for: .milliseconds(5))
        }
    }
}
