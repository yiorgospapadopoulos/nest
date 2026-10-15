import Foundation
import Observation

/// A key the composer handles itself rather than leaving to the text field.
public enum ComposerKey: Sendable, Hashable {
    case up, down, tab, escape
    case enter(shift: Bool)
}

/// What a key does in the composer.
public enum ComposerKeyAction: Sendable, Hashable {
    /// Moves the suggestion highlight by this many rows.
    case move(Int)
    /// Puts the highlighted suggestion into the text.
    case insert
    /// Closes the suggestion list.
    case close
    case send
    /// Stops the running turn.
    case interrupt
    /// Puts the chat's last sent message back into the empty field.
    case recall
    /// Esc Esc while no turn runs: rewind to before one of the user's messages (B59).
    case rewind
    /// The text field handles the key as usual.
    case ignore

    /// An open suggestion list takes the arrows, Tab, Return and Esc; otherwise Return
    /// sends (Shift-Return adds a line), Esc interrupts a running turn, a `repeated` Esc
    /// (`EscapeRepeat`) rewinds and Up arrow in an empty field recalls the last message.
    public static func of(
        _ key: ComposerKey, suggesting: Bool, isEmpty: Bool, working: Bool,
        repeated: Bool = false
    ) -> ComposerKeyAction {
        if suggesting {
            switch key {
            case .up: return .move(-1)
            case .down: return .move(1)
            case .tab, .enter(shift: false): return .insert
            case .escape: return .close
            case .enter(shift: true): return .ignore
            }
        }
        switch key {
        case .enter(shift: false): return .send
        case .escape where working: return .interrupt
        case .escape where repeated: return .rewind
        case .up where isEmpty: return .recall
        default: return .ignore
        }
    }
}

/// Esc pressed twice in quick succession, as Claude Code's Esc Esc.
public struct EscapeRepeat: Sendable {
    /// The longest pause between the two presses.
    public static let window: TimeInterval = 0.6
    private var last: Date?

    public init() {}

    /// Whether this press completes a pair.
    public mutating func press(at now: Date) -> Bool {
        if let last, now.timeIntervalSince(last) <= Self.window {
            self.last = nil
            return true
        }
        last = now
        return false
    }
}

/// The composer's main button. Text typed while a turn runs is sent into it, as in
/// Claude Code (B59).
public enum SendButtonMode: Sendable, Hashable {
    case send
    /// An empty field while a turn runs offers to stop it.
    case interrupt

    public static func of(working: Bool, hasText: Bool) -> SendButtonMode {
        working && !hasText ? .interrupt : .send
    }
}

/// What a composer keeps once its message is sent: the text typed while the send was in
/// flight.
public enum SentDraft {
    /// `current` without the `sent` text it starts with; when the user changed the sent
    /// part meanwhile, all of it stays, so nothing typed is lost.
    public static func remainder(of current: String, after sent: String) -> String {
        guard current.hasPrefix(sent) else { return current }
        return String(current.dropFirst(sent.count).drop { $0.isWhitespace })
    }
}

/// The last message the user sent in each chat from this app, for Up arrow.
@MainActor @Observable
public final class SentMessages {
    private var last: [String: String] = [:]

    public init() {}

    public func record(_ text: String, chat: String) {
        last[chat] = text
    }

    /// The message sent from here, or else the newest user message of the transcript.
    public func last(chat: String, transcript: [TranscriptItem]) -> String? {
        if let sent = last[chat] {
            return sent
        }
        for item in transcript.reversed() {
            if case .user(let text, _) = item.content, !text.isEmpty {
                return text
            }
        }
        return nil
    }
}
