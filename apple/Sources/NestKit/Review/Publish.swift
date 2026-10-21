import Foundation
import Observation

/// A step of approving a review, named as the daemon names them in `git.failed`.
public enum PublishStepKind: String, Sendable, CaseIterable {
    case commit, push, pr

    public var title: String {
        switch self {
        case .commit: "Commit"
        case .push: "Push"
        case .pr: "Open pull request"
        }
    }
}

/// A review rejected before reviews lost Reject (B56) only resolved the review; its
/// transcript line says the changes stayed (B54).
public enum RejectConsequence {
    /// The transcript's line for a rejected review.
    public static let transcript = "Rejected. Changes kept, nothing committed"
}

/// What the approve sheet edits: the commit message and whether to open a pull request.
/// A worktree chat without a pull request pushes to open one (B56); one whose pull request
/// is open pushes to it, unless the user chose Approve and commit (B101); otherwise
/// Approve commits and never pushes.
public struct PublishForm: Sendable, Hashable {
    public var commitMessage: String
    public var openPR = true
    public var prTitle = ""
    public var prBody = ""
    /// The push address the user confirmed after approving was refused for it (I-008).
    public var confirmRemoteURL: String?
    public let mode: SessionMode
    /// The chat has a pull request, open or not.
    public let hasPullRequest: Bool
    /// The number of the chat's open pull request, which Approve pushes to (B101).
    public let pullRequest: Int?
    /// With an open pull request: push to it, or only commit (Approve and commit).
    public var pushToPR = true
    /// In-place sessions commit only the reviewed files.
    public let files: [String]
    /// Sent review threads the push to the open pull request replies on (B101).
    let threadsToReply: Int

    /// Starts from the session's title as the commit message.
    public init(approval: Approval, session: Session?) {
        commitMessage = approval.title
        mode = session?.mode ?? .worktree
        hasPullRequest = session?.prURL != nil
        pullRequest = Self.openPullRequest(of: session)
        files = approval.review?.paths ?? []
        threadsToReply = session?.review?.threadsToReply ?? 0
    }

    /// A worktree chat's open pull request: its number as Nest last read it, or from its
    /// address before Nest read it.
    static func openPullRequest(of session: Session?) -> Int? {
        guard let session, session.mode != .inPlace, let url = session.prURL else { return nil }
        guard let pr = session.pr else {
            return url.split(separator: "/").last.flatMap { Int($0) }
        }
        return pr.state == .open ? pr.number : nil
    }

    /// Whether the chat's Approve pushes: a worktree chat without a pull request, to open
    /// one, or with an open one, to update it.
    public static func pushes(for session: Session?) -> Bool {
        openPullRequest(of: session) != nil || (session?.mode != .inPlace && session?.prURL == nil)
    }

    /// The Approve button outside the sheet, on the review card and the changes sheet.
    public static func approveTitle(for session: Session?) -> String {
        if let number = openPullRequest(of: session) {
            return pushTitle(number)
        }
        return pushes(for: session) ? "Approve and open PR" : commitTitle
    }

    /// The review card's quiet line under "Approve and push to #8".
    public static func replyNote(for session: Session?) -> String? {
        guard openPullRequest(of: session) != nil else { return nil }
        return replyNote(threads: session?.review?.threadsToReply ?? 0)
    }

    /// "Also replies on 2 review threads with the commit, without resolving them."
    static func replyNote(threads: Int) -> String? {
        guard threads > 0 else { return nil }
        return
            "Also replies on \(threads) review thread\(threads == 1 ? "" : "s") with the commit, without resolving them."
    }

    /// The plain button beside "Approve and push to #8", which commits only.
    public static let commitTitle = "Approve and commit"

    /// Whether "Approve and commit" shows beside the Approve button: only while it pushes to
    /// an open pull request.
    public static func offersCommitOnly(for session: Session?) -> Bool {
        openPullRequest(of: session) != nil
    }

    /// "Approve and push to #8".
    public static func pushTitle(_ number: Int) -> String { "Approve and push to #\(number)" }

    /// In-place sessions work on the checkout's own branch, and a chat with a pull request
    /// already has one, so neither opens one.
    public var canOpenPR: Bool { mode != .inPlace && !hasPullRequest }

    /// Approve opens a pull request.
    var opensPR: Bool { canOpenPR && openPR }

    /// Approve pushes to the open pull request's branch (B101).
    public var pushesToPR: Bool { pullRequest != nil && pushToPR }

    /// Approve pushes the branch, to open the pull request or update the open one.
    public var pushes: Bool { opensPR || pushesToPR }

    /// The sheet's title and Approve button.
    public var title: String {
        if pushesToPR, let pullRequest {
            return Self.pushTitle(pullRequest)
        }
        return opensPR ? "Approve and open PR" : Self.commitTitle
    }

    /// What Approve does with the pull request, when it opens none.
    public var note: String? {
        if mode == .inPlace {
            return
                "This chat works in the project folder, so its files are committed on the current branch, without pushing or a pull request."
        }
        if let pullRequest {
            return pushToPR
                ? "Approve commits and pushes to the pull request's branch, updating #\(pullRequest)."
                : "This chat's pull request is already open. Approve and commit commits to its branch without pushing; the pull request stays as it is."
        }
        if hasPullRequest {
            return
                "This chat's pull request is no longer open. Approve commits to its branch without pushing."
        }
        return nil
    }

    /// The sheet's grey line under the note while Approve pushes to the open pull request
    /// and sent threads wait for Nest's reply.
    public var replyNote: String? {
        pushesToPR ? Self.replyNote(threads: threadsToReply) : nil
    }

    /// The toast once approving went through.
    public func done(_ title: String) -> String {
        if pushesToPR, let pullRequest {
            return "Pushed \(title) to #\(pullRequest)"
        }
        return opensPR
            ? "Opened a pull request for \(title)" : "Committed \(title) without pushing"
    }

    public var canSubmit: Bool {
        !commitMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// The steps the daemon will run, in order.
    public var steps: [PublishStepKind] {
        opensPR ? [.commit, .push, .pr] : pushes ? [.commit, .push] : [.commit]
    }

    public var request: ApproveRequest {
        func optional(_ text: String) -> String? {
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }
        return ApproveRequest(
            commitMessage: commitMessage.trimmingCharacters(in: .whitespacesAndNewlines),
            files: mode == .inPlace ? files : nil, push: pushes, openPR: opensPR,
            prTitle: opensPR ? optional(prTitle) : nil,
            prBody: opensPR ? optional(prBody) : nil,
            confirmRemoteURL: pushes ? confirmRemoteURL : nil)
    }
}

public enum PublishStepState: Sendable, Hashable {
    case pending, running, done
    /// The step's error output, or the failure's message.
    case failed(String)
}

public struct PublishStep: Sendable, Hashable, Identifiable {
    public let kind: PublishStepKind
    public var state: PublishStepState

    public var id: PublishStepKind { kind }
}

/// The progress of one approve call, step by step, from the daemon's git events.
@MainActor @Observable
public final class PublishProgress {
    public private(set) var steps: [PublishStep]
    public private(set) var isRunning = false
    /// Set when the call failed; the review stays pending and can be approved again.
    public private(set) var failure: APIError?
    /// The session as the successful call returned it.
    public private(set) var result: Session?

    public init(steps: [PublishStepKind]) {
        self.steps = steps.map { PublishStep(kind: $0, state: .pending) }
    }

    public var failedStep: PublishStep? {
        steps.first { if case .failed = $0.state { true } else { false } }
    }

    func start() {
        isRunning = true
        failure = nil
        result = nil
        steps = steps.map { PublishStep(kind: $0.kind, state: .pending) }
        markRunning(from: 0)
    }

    /// A step's event: it and every step before it are done, and the next one runs.
    func complete(_ kind: PublishStepKind) {
        guard let index = steps.firstIndex(where: { $0.kind == kind }) else { return }
        for earlier in 0...index {
            steps[earlier].state = .done
        }
        markRunning(from: index + 1)
    }

    func fail(step kind: PublishStepKind?, message: String) {
        guard
            let index = kind.flatMap({ kind in steps.firstIndex { $0.kind == kind } })
                ?? steps.firstIndex(where: { $0.state == .running }) ?? steps.indices.first
        else { return }
        // The daemon runs steps in order, so the ones before the failure went through.
        for earlier in steps.indices where earlier < index {
            steps[earlier].state = .done
        }
        steps[index].state = .failed(message)
        for later in steps.indices where later > index {
            steps[later].state = .pending
        }
    }

    func finish(_ session: Session) {
        steps = steps.map { PublishStep(kind: $0.kind, state: .done) }
        result = session
        isRunning = false
    }

    /// A refusal (409) ran no step: the steps stay pending and the failure says why.
    func finish(_ error: APIError) {
        if error.isConflict {
            steps = steps.map { PublishStep(kind: $0.kind, state: .pending) }
        } else if case .gitFailed(_, let step, let stderr) = error {
            let message = stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            fail(
                step: PublishStepKind(rawValue: step),
                message: message.isEmpty ? error.message : message)
        } else if failedStep == nil {
            fail(step: nil, message: error.message)
        }
        failure = error
        isRunning = false
    }

    private func markRunning(from index: Int) {
        if steps.indices.contains(index) {
            steps[index].state = .running
        }
    }
}
