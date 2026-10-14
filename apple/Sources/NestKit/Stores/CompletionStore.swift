import Foundation
import Observation

/// The composer's suggestions: slash commands of a chat (or of its project for a new
/// chat), asked for once each, and files for "@" mentions, where the latest search wins.
@MainActor @Observable
public final class CompletionStore {
    /// Commands by source: "session:<id>" or "repo:<name>".
    private var commands: [String: [SlashCommand]] = [:]
    private var requested: Set<String> = []
    /// The latest file search's answer.
    private var found: (session: String, files: [String])?
    @ObservationIgnored private(set) var latestSearch: String?

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    /// Asks for the commands once per chat (or project, without a session). An empty list
    /// or a failure is asked for again next time, since the first run may not have
    /// reported its commands yet.
    public func loadCommands(session: String?, repo: String) async {
        let key = Self.source(session: session, repo: repo)
        guard !requested.contains(key) else { return }
        requested.insert(key)
        do {
            let list =
                if let session {
                    try await api.sessionCommands(session)
                } else {
                    try await api.repoCommands(repo)
                }
            commands[key] = list.commands
            if list.commands.isEmpty {
                requested.remove(key)
            }
        } catch {
            requested.remove(key)
        }
    }

    /// Searches the session's files; an answer that a newer search overtook is dropped,
    /// and a failure (such as a missing folder) gives no suggestions.
    public func searchFiles(session: String, query: String) async {
        let key = "\(session)\n\(query)"
        latestSearch = key
        let files = (try? await api.sessionFiles(session, query: query)) ?? []
        guard latestSearch == key else { return }
        found = (session, files)
    }

    /// The suggestions for the token at the caret; nil when nothing is being completed.
    /// Files need a session, so a new chat completes commands, and pixies where
    /// `mentions` offers them: the pixies and teams the chat may call, which "@" lists
    /// before the files, filtered by what was typed (B40).
    public func suggestions(
        text: String, caret: Int, session: String?, repo: String,
        mentions: [PixieMention]? = nil
    ) -> CompletionList? {
        guard let trigger = CompletionTrigger.at(text, caret: caret) else { return nil }
        switch trigger.kind {
        case .command:
            let known = commands[Self.source(session: session, repo: repo)] ?? []
            return .commands(known, for: trigger, in: text)
        case .file:
            guard session != nil || mentions != nil else { return nil }
            let files = found.flatMap { $0.session == session ? $0.files : nil } ?? []
            guard let mentions else { return .files(files, for: trigger, in: text) }
            let matching = PixieMentions.matching(mentions, query: trigger.query)
            return .mentions(matching, files: files, for: trigger, in: text)
        }
    }

    static func source(session: String?, repo: String) -> String {
        session.map { "session:\($0)" } ?? "repo:\(repo)"
    }
}
