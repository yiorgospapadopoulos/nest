import Foundation

/// The system's answer to one permission Nest asks for.
public enum SystemPermission: Sendable, Equatable {
    case allowed, refused, restricted, notAsked
}

/// What only the app can answer (B130): the daemon's `notifications`, `dictation` and
/// `permissions` checks say "Checked in the app."; on the Mac these replace them.
public struct SystemAnswers: Sendable, Equatable {
    public var notifications: SystemPermission
    public var microphone: SystemPermission
    public var speech: SystemPermission
    public var accessibility: Bool

    public init(
        notifications: SystemPermission = .notAsked, microphone: SystemPermission = .notAsked,
        speech: SystemPermission = .notAsked, accessibility: Bool = false
    ) {
        self.notifications = notifications
        self.microphone = microphone
        self.speech = speech
        self.accessibility = accessibility
    }

    private static let settings = "x-apple.systempreferences:com.apple"
    public static let notificationSettings = "\(settings).Notifications-Settings.extension"
    public static let microphoneSettings = "\(settings).preference.security?Privacy_Microphone"
    public static let speechSettings =
        "\(settings).preference.security?Privacy_SpeechRecognition"
    public static let accessibilitySettings =
        "\(settings).preference.security?Privacy_Accessibility"

    /// The list with the app's answers in place of the daemon's.
    public func filling(_ checks: [SetupCheck]) -> [SetupCheck] {
        checks.map { check in
            var check = check
            switch check.id {
            case "notifications": answerNotifications(&check)
            case "dictation": answerDictation(&check)
            case "permissions": answerPermissions(&check)
            default: break
            }
            return check
        }
    }

    /// The checks only the app can make, answered, for the bug report: the daemon puts them
    /// in place of its own "Checked in the app." (B130).
    public var reportChecks: [SetupCheck] {
        filling([
            SetupCheck(id: "notifications", title: "Notifications", state: .notApplicable),
            SetupCheck(id: "dictation", title: "Dictation", state: .notApplicable),
            SetupCheck(id: "permissions", title: "Mac permissions", state: .notApplicable),
        ])
    }

    /// "Microphone: refused", as the guide's and Check Nest's lines say it.
    public static func line(_ name: String, _ answer: SystemPermission) -> String {
        switch answer {
        case .allowed: "\(name): allowed"
        case .refused: "\(name): refused"
        case .restricted: "\(name): restricted on this Mac"
        case .notAsked: "\(name): not asked yet"
        }
    }

    private func answerNotifications(_ check: inout SetupCheck) {
        check.message = Self.line("Notifications", notifications)
        check.state = Self.state(of: [notifications])
        check.fix =
            notifications == .refused
            ? .init(kind: .link, value: Self.notificationSettings) : nil
        if notifications == .allowed {
            check.message = ""
            check.detail = "Allowed"
        }
    }

    private func answerDictation(_ check: inout SetupCheck) {
        let answers = [microphone, speech]
        check.state = Self.state(of: answers)
        let lines = [("Microphone", microphone), ("Speech Recognition", speech)]
            .filter { $0.1 != .allowed }
            .map { Self.line($0.0, $0.1) }
        check.message = lines.joined(separator: ". ")
        check.fix = nil
        if microphone == .refused {
            check.fix = .init(kind: .link, value: Self.microphoneSettings)
        } else if speech == .refused {
            check.fix = .init(kind: .link, value: Self.speechSettings)
        }
        if lines.isEmpty {
            check.detail = "Allowed"
        }
    }

    /// Accessibility, the one permission with no check of its own; the island works without it.
    private func answerPermissions(_ check: inout SetupCheck) {
        if accessibility {
            check.state = .ok
            check.message = ""
            check.detail = "Accessibility allowed"
        } else {
            check.state = .notApplicable
            check.message = "Accessibility is off, so the island keeps beside the notch."
            check.fix = .init(kind: .link, value: Self.accessibilitySettings)
        }
    }

    /// Refused or restricted is a fault; not asked yet is only a warning.
    private static func state(of answers: [SystemPermission]) -> SetupCheck.State {
        if answers.allSatisfy({ $0 == .allowed }) {
            return .ok
        }
        return answers.contains(.refused) || answers.contains(.restricted) ? .missing : .warning
    }
}
