import Foundation
import Observation

/// Each project's open GitHub issues (B101), read when its start screen appears: all of
/// them or the user's, as chosen per project on this Mac.
@MainActor @Observable
public final class IssuesStore {
    public private(set) var lists: [String: IssueList] = [:]
    /// The switch's choices by project, as stored.
    private var chosen: [String: IssueShow] = [:]

    let api: any NestAPI
    @ObservationIgnored let store: any KeyValueStore

    public init(api: any NestAPI, store: any KeyValueStore = UserDefaultsStore()) {
        self.api = api
        self.store = store
    }

    /// Reads the repo's issues; a failure keeps the ones it had, for the next appearance to
    /// read again.
    public func load(_ repo: String, refresh: Bool = false) async {
        guard
            let list = try? await api.issues(
                repo: repo, refresh: refresh, show: choice(repo))
        else { return }
        lists[repo] = list
    }

    /// The switch: the user's choice for the project, else what the daemon answered.
    public func show(_ repo: String) -> IssueShow {
        choice(repo) ?? lists[repo]?.show ?? .all
    }

    /// Remembers the choice on this Mac and reads the issues again.
    public func setShow(_ show: IssueShow, for repo: String) async {
        chosen[repo] = show
        store.set(show.rawValue, forKey: Self.key(repo))
        await load(repo)
    }

    private func choice(_ repo: String) -> IssueShow? {
        chosen[repo]
            ?? store.string(forKey: Self.key(repo)).flatMap(IssueShow.init(rawValue:))
    }

    private static func key(_ repo: String) -> String { "issues.show.\(repo)" }

    public func list(_ repo: String) -> IssueList? {
        lists[repo]
    }
}
