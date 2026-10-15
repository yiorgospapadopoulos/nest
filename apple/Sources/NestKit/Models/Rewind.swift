import Foundation

/// What a rewind puts back, as Claude Code's Esc Esc offers it (B59).
public enum RewindRestore: String, Codable, Sendable, CaseIterable {
    /// Claude forgets the message and everything after it; files stay.
    case conversation
    /// Only the files go back, from Claude Code's file checkpoints (IMP-02).
    case code
    case both

    public var label: String {
        switch self {
        case .conversation: "Restore conversation"
        case .code: "Restore code"
        case .both: "Restore conversation and code"
        }
    }

    /// What the choice does, in a sentence under the options.
    public var scope: String {
        switch self {
        case .conversation:
            "Claude forgets this message and everything after it. Files stay as they are, and the message goes back into the composer."
        case .code:
            "Only files are restored. The conversation stays as it is, and Claude is not told."
        case .both:
            "Files go back to before this message, and Claude forgets it and everything after it. The message goes back into the composer."
        }
    }
}

/// A user message taken back by a rewind or a fork, for the composer.
public struct RestoredMessage: Sendable, Hashable {
    public var text: String
    /// Attachments the chat owns; their ids are sent again with the message.
    public var attachments: [Attachment]

    public init(text: String, attachments: [Attachment]) {
        self.text = text
        self.attachments = attachments
    }

    /// A draft with text in it is not replaced without asking.
    public func needsAsking(draft: String) -> Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// Keep both: the restored message, then the draft.
    public func combined(with draft: String) -> String {
        draft.isEmpty ? text : "\(text)\n\n\(draft)"
    }
}

/// `GET` and `POST /api/sessions/{id}/rewind`: what restoring to before a user message
/// changes (the files part, from Claude Code's file checkpoints) and, for a conversation
/// rewind, the message for the composer.
public struct RewindPreview: Decodable, Sendable, Hashable {
    public var canRewind: Bool
    /// The files that would change, when the daemon lists them.
    public var files: [String]
    public var filesChanged: Int
    public var insertions: Int
    public var deletions: Int
    /// Why it cannot be done, when it cannot.
    public var error: String?
    public var restore: RewindRestore?
    /// The rewound message, for `conversation` and `both`.
    public var text: String?
    public var attachments: [Attachment]

    public init(
        canRewind: Bool, files: [String] = [], filesChanged: Int? = nil, insertions: Int = 0,
        deletions: Int = 0, error: String? = nil, restore: RewindRestore? = nil,
        text: String? = nil, attachments: [Attachment] = []
    ) {
        self.canRewind = canRewind
        self.files = files
        self.filesChanged = filesChanged ?? files.count
        self.insertions = insertions
        self.deletions = deletions
        self.error = error
        self.restore = restore
        self.text = text
        self.attachments = attachments
    }

    enum CodingKeys: String, CodingKey {
        case insertions, deletions, error, restore, text, attachments
        case canRewind = "can_rewind"
        case filesChanged = "files_changed"
    }

    /// `files_changed` is Claude Code's list of paths, or a count.
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        canRewind = try container.decode(Bool.self, forKey: .canRewind)
        if let paths = try? container.decodeIfPresent([String].self, forKey: .filesChanged) {
            files = paths
            filesChanged = paths.count
        } else {
            files = []
            filesChanged = try container.decodeIfPresent(Int.self, forKey: .filesChanged) ?? 0
        }
        insertions = try container.decodeIfPresent(Int.self, forKey: .insertions) ?? 0
        deletions = try container.decodeIfPresent(Int.self, forKey: .deletions) ?? 0
        error = try container.decodeIfPresent(String.self, forKey: .error)
        restore = try container.decodeIfPresent(RewindRestore.self, forKey: .restore)
        text = try container.decodeIfPresent(String.self, forKey: .text)
        attachments = try container.decodeIfPresent([Attachment].self, forKey: .attachments) ?? []
    }

    /// "2 files change: +12 -4", or that nothing changed since the message.
    public var summary: String {
        guard filesChanged > 0 else { return "No files changed since this message." }
        let noun = filesChanged == 1 ? "1 file changes" : "\(filesChanged) files change"
        return "\(noun): +\(insertions) -\(deletions)"
    }

    /// The message a conversation rewind gave back.
    public var restoredMessage: RestoredMessage? {
        text.map { RestoredMessage(text: $0, attachments: attachments) }
    }
}

/// `POST /api/sessions/{id}/fork`: the new chat and the forked message for its composer.
public struct ForkedChat: Decodable, Sendable, Hashable {
    public var session: Session
    public var message: RestoredMessage

    enum CodingKeys: String, CodingKey {
        case session, text, attachments
    }

    public init(session: Session, message: RestoredMessage) {
        self.session = session
        self.message = message
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        session = try container.decode(Session.self, forKey: .session)
        message = RestoredMessage(
            text: try container.decode(String.self, forKey: .text),
            attachments: try container.decode([Attachment].self, forKey: .attachments))
    }
}

/// Why the rewind sheet opened: Rewind on a message, or Edit, which rewinds the
/// conversation and asks only when files changed since.
public enum RewindPurpose: Sendable, Hashable {
    case rewind, edit
}

/// Rewind to before a user message: previews of the files and the conversation, the
/// user's choice, then the rewind (B59, IMP-02).
@MainActor @Observable
public final class RewindFlow {
    public let session: String
    /// The user message's event id.
    public let message: Int
    public let purpose: RewindPurpose
    /// The files part, from `restore=code`.
    public private(set) var files: RewindPreview?
    private var conversation: RewindPreview?
    /// Why a preview could not be read.
    private var loadFailure: String?
    private var loaded = false
    public private(set) var selected: RewindRestore?
    /// Why the rewind failed.
    public private(set) var failure: String?
    public private(set) var isRestoring = false

    let api: any NestAPI

    public init(
        session: String, message: Int, purpose: RewindPurpose = .rewind, api: any NestAPI
    ) {
        self.session = session
        self.message = message
        self.purpose = purpose
        self.api = api
    }

    /// The daemon rewinds while no turn runs: idle, after Stop or a failure, and not in
    /// an archived chat (audit BUG-104), and never in a pixie's chat, whose runs start
    /// fresh so the earlier ones' checkpoints are gone (D072).
    public static func isAvailable(for session: Session?) -> Bool {
        guard let session, !session.isArchived, session.pixieID == nil else { return false }
        return [.idle, .interrupted, .failed].contains(session.state)
    }

    public var isLoading: Bool { !loaded }

    /// The options the sheet shows; Edit always rewinds the conversation.
    public var choices: [RewindRestore] {
        purpose == .edit ? [.conversation, .both] : [.conversation, .code, .both]
    }

    /// Why the option cannot be chosen; nil when it can.
    public func reason(_ restore: RewindRestore) -> String? {
        switch restore {
        case .conversation:
            guard let conversation else { return loadFailure }
            return conversation.canRewind
                ? nil
                : conversation.error
                    ?? "The conversation cannot be rewound to before this message."
        case .code:
            guard let files else { return loadFailure }
            guard files.canRewind else {
                return files.error ?? "The files cannot be restored to before this message."
            }
            return files.filesChanged == 0 ? "Nothing to restore" : nil
        case .both:
            return reason(.conversation) ?? reason(.code)
        }
    }

    /// Edit asks only when files changed since the message: they could go back too.
    public var needsChoice: Bool {
        purpose == .edit && reason(.code) == nil
    }

    public func select(_ restore: RewindRestore) {
        guard reason(restore) == nil else { return }
        selected = restore
    }

    public var canConfirm: Bool {
        selected != nil && !isRestoring
    }

    /// The confirm button's title.
    public var confirmLabel: String {
        if isRestoring {
            return "Restoring…"
        }
        return selected?.label ?? "Restore"
    }

    /// Reads both previews; the first option that can be done is chosen, both parts
    /// first when Rewind opened it, as in Claude Code.
    public func load() async {
        async let code = preview(.code)
        async let talk = preview(.conversation)
        let (codeResult, talkResult) = await (code, talk)
        loadFailure = nil
        for case .failure(let error) in [codeResult, talkResult] {
            loadFailure = Self.describe(error)
        }
        files = try? codeResult.get()
        conversation = try? talkResult.get()
        loaded = true
        let order: [RewindRestore] =
            purpose == .edit ? [.conversation] : [.both, .conversation, .code]
        selected = order.first { reason($0) == nil }
    }

    private func preview(_ restore: RewindRestore) async -> Result<RewindPreview, any Error> {
        do {
            return .success(try await api.rewindPreview(session, message: message, restore: restore))
        } catch {
            return .failure(error)
        }
    }

    /// Rewinds as chosen; the daemon's reply, with the message for the composer, or nil
    /// when it failed (`failure` says why).
    public func confirm() async -> RewindPreview? {
        guard let selected, canConfirm else { return nil }
        isRestoring = true
        defer { isRestoring = false }
        do {
            let reply = try await api.rewind(session, message: message, restore: selected)
            failure = nil
            return reply
        } catch {
            failure = Self.describe(error)
            return nil
        }
    }

    private static func describe(_ error: any Error) -> String {
        (error as? APIError)?.message ?? error.localizedDescription
    }
}
