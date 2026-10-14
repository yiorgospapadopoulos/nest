import Foundation

/// The palette's search of chat history (D035): waits for typing to pause, and answers
/// only the newest query, so a slow answer to an older one never shows.
@MainActor
public final class MessageSearch {
    /// Shorter queries are not sent.
    public nonisolated static let minimumLength = 2
    /// How long typing must pause before the daemon is asked.
    public static let delay = 0.2
    public static let limit = 20

    let api: any NestAPI
    let sleeper: any Sleeper
    /// Counts queries; an answer whose number is no longer the newest is dropped.
    private var generation = 0

    public init(api: any NestAPI, sleeper: any Sleeper = TaskSleeper()) {
        self.api = api
        self.sleeper = sleeper
    }

    /// The hits for the typed text after the pause, none when the search failed; nil when
    /// the text is too short or a newer query came in meanwhile.
    public func results(for text: String) async -> SearchResults? {
        generation += 1
        let ticket = generation
        let query = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard query.count >= Self.minimumLength else { return nil }
        guard (try? await sleeper.sleep(seconds: Self.delay)) != nil, ticket == generation
        else { return nil }
        let results = try? await api.search(query: query, repo: nil, limit: Self.limit)
        guard ticket == generation else { return nil }
        return results ?? SearchResults(hits: [], indexing: false)
    }
}
