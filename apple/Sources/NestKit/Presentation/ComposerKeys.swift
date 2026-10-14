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
    /// The text field handles the key as usual.
    case ignore

    /// An open suggestion list takes the arrows, Tab, Return and Esc; otherwise Return
    /// sends (Shift-Return adds a line), Esc interrupts a running turn and Up arrow in an
    /// empty field recalls the last message.
    public static func of(
        _ key: ComposerKey, suggesting: Bool, isEmpty: Bool, working: Bool
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
        case .up where isEmpty: return .recall
        default: return .ignore
        }
    }
}

/// The composer's main button.
public enum SendButtonMode: Sendable, Hashable {
    case send
    /// Text typed while a turn runs is queued for when it ends.
    case queue
    /// An empty field while a turn runs offers to stop it.
    case interrupt

    public static func of(working: Bool, hasText: Bool) -> SendButtonMode {
        guard working else { return .send }
        return hasText ? .queue : .interrupt
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
