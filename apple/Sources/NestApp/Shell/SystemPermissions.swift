import AppKit
import NestKit
import Observation

/// The system's answers the daemon cannot give (B130): notifications, the microphone and
/// speech recognition. Read when asked and whenever the window comes back, as they change in
/// System Settings.
@MainActor @Observable
final class SystemPermissions {
    private(set) var notifications = SystemPermission.notAsked
    private(set) var microphone = SystemPermission.notAsked
    private(set) var speech = SystemPermission.notAsked

    func refresh() async {
        notifications = await Notifier.answer()
        microphone = DictationAccess.microphone
        speech = DictationAccess.speech
    }

    /// The button that asks now, instead of at the first dictation.
    func askDictation() async {
        guard DictationAccess.canAsk else { return }
        _ = await DictationAccess.request()
        await refresh()
    }

    func askNotifications() async {
        guard Notifier.canNotify else { return }
        await Notifier.ask()
        await refresh()
    }

    func answers(accessibility: Bool) -> SystemAnswers {
        SystemAnswers(
            notifications: notifications, microphone: microphone, speech: speech,
            accessibility: accessibility)
    }

    func openSettings(_ address: String) {
        if let url = URL(string: address) {
            NSWorkspace.shared.open(url)
        }
    }
}
