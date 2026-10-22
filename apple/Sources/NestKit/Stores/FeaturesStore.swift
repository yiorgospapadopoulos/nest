import Foundation
import Observation

/// Settings > Features (B103): the catalog with what is new on this device, which groups
/// are open, and the report of the features the page shows.
@MainActor @Observable
public final class FeaturesStore {
    /// Nil until loaded.
    public private(set) var catalog: FeaturesCatalog?
    /// The user's own open or close, by group id, as stored on this Mac.
    private var choices: [String: Bool]
    /// Ids reported in this run of the app; the daemon keeps only the first report anyway.
    @ObservationIgnored private var reported: Set<String> = []
    /// What was new when the page showed during this visit to Settings; it keeps its badge
    /// until Settings opens again, though the daemon stops calling it new once it is shown.
    private var visitNew: Set<String> = []

    let api: any NestAPI
    @ObservationIgnored let store: any KeyValueStore

    static let groupsKey = "nest.features.groups"
    public static let introBase =
        "What makes Nest different, by area. The README has every detail."

    /// An unreadable stored value is ignored.
    public init(api: any NestAPI, store: any KeyValueStore) {
        self.api = api
        self.store = store
        choices =
            store.string(forKey: Self.groupsKey)
            .flatMap { try? JSONDecoder().decode([String: Bool].self, from: Data($0.utf8)) }
            ?? [:]
    }

    public func load() async throws {
        catalog = try await api.features()
    }

    /// How many features show "New"; the sidebar shows it while above zero, so it lasts the
    /// visit to Settings with the badges.
    public var newCount: Int {
        (catalog?.groups ?? []).flatMap(\.features).count(where: isNew)
    }

    /// Whether the feature shows "New": the daemon's latest answer says so, or it did when
    /// the page showed during this visit to Settings.
    public func isNew(_ feature: Feature) -> Bool {
        visitNew.contains(feature.id) || daemonNew.contains(feature.id)
    }

    /// What the latest answer calls new.
    private var daemonNew: Set<String> {
        Set((catalog?.groups ?? []).flatMap(\.features).filter(\.isNew).map(\.id))
    }

    /// Whether one of the group's features shows "New"; its row shows a dot.
    public func hasNew(_ group: FeatureGroup) -> Bool {
        group.features.contains(where: isNew)
    }

    /// The user's choice, else open while the group has something new.
    public func isOpen(_ group: FeatureGroup) -> Bool {
        choices[group.id] ?? hasNew(group)
    }

    /// The page shows: remembers what is new now, for the rest of the visit, then reports
    /// the features in open groups. A failed report is tried again when the page next shows
    /// or a group opens.
    public func pageShown() async {
        visitNew.formUnion(daemonNew)
        try? await markShown(shownIDs)
    }

    /// Settings opens: a new visit, so what was new during the last one is not any more.
    public func beginVisit() {
        visitNew = []
    }

    /// Opens or closes the group and remembers it on this Mac.
    public func toggle(_ group: FeatureGroup) {
        choices[group.id] = !isOpen(group)
        if let data = try? JSONEncoder().encode(choices) {
            store.set(String(decoding: data, as: UTF8.self), forKey: Self.groupsKey)
        }
    }

    /// The features the page shows: those in open groups, in order.
    public var shownIDs: [String] {
        (catalog?.groups ?? []).filter(isOpen).flatMap { $0.features.map(\.id) }
    }

    /// Reports the ids not reported yet and takes the answer as the new catalog; a failed
    /// report is tried again next time.
    public func markShown(_ ids: [String]) async throws {
        let fresh = ids.filter { !reported.contains($0) }
        guard !fresh.isEmpty else { return }
        catalog = try await api.markFeaturesShown(fresh)
        reported.formUnion(fresh)
    }

    /// The page's grey intro, with how many features show "New" while any do.
    public var intro: String {
        newCount > 0 ? "\(Self.introBase) \(newCount) new since your last update." : Self.introBase
    }

    /// The line under the groups, once loaded.
    public var footer: String? {
        guard let total = catalog?.total else { return nil }
        let count = total == 1 ? "1 feature" : "\(total) features"
        return "\(count). New ones show \"New\" until you close Settings."
    }

    /// The group and feature names, for the settings search.
    public var labels: [String] {
        (catalog?.groups ?? []).flatMap { [$0.name] + $0.features.map(\.name) }
    }
}
