import AppKit
import NestKit
import SwiftUI

/// Every command's shortcut by group: Change, then the new keys; Escape cancels (B81).
struct ShortcutsPage: View {
    @Environment(Shell.self) private var shell
    @State private var recorder = ShortcutRecorder()

    var body: some View {
        let shortcuts = shell.shortcuts
        ForEach(ShortcutGroup.allCases, id: \.self) { group in
            SettingsSection(title: group.rawValue) {
                ForEach(group.actions, id: \.self) { action in
                    ShortcutRow(action: action, recorder: recorder)
                }
            }
        }
        Button("Restore defaults") {
            recorder.stop()
            shortcuts.restoreDefaults()
        }
        .buttonStyle(.nest(.soft))
        .disabled(!shortcuts.hasChanges)
        .padding(.top, 14)
        .onDisappear { recorder.stop() }
    }
}

private struct ShortcutRow: View {
    let action: ShortcutAction
    let recorder: ShortcutRecorder
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    var body: some View {
        let shortcuts = shell.shortcuts
        let recording = recorder.action == action
        SettingsRow(label: action.title) {
            if recorder.refusal?.action == action, let message = recorder.refusal?.message {
                Text(message)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(StatusTone.failed.color)
                    .lineLimit(1)
            }
            Text(recording ? "Press keys" : shortcuts.shortcut(for: action).display)
                .font(.mono(11, .medium))
                .foregroundStyle(recording ? Palette.t2 : Palette.t1)
                .padding(.horizontal, 7)
                .padding(.vertical, 2)
                .frame(minWidth: 44)
                .background(Palette.soft, in: .rounded(5))
                .overlay {
                    if recording {
                        RoundedRectangle.rounded(5).strokeBorder(accent.focus, lineWidth: 1)
                    }
                }
            Button(recording ? "Cancel" : "Change") {
                if recording {
                    recorder.stop()
                } else {
                    recorder.start(action, in: shortcuts)
                }
            }
            .buttonStyle(.nest(.soft))
            .accessibilityLabel(recording ? "Cancel" : "Change \(action.title)")
        }
    }
}

/// Reads the next key press while a command's shortcut is being recorded, before the menus
/// can act on it.
@MainActor @Observable
final class ShortcutRecorder {
    private(set) var action: ShortcutAction?
    /// Why the last keys were refused, for that command's row.
    private(set) var refusal: (action: ShortcutAction, message: String)?
    @ObservationIgnored private var monitor: Any?

    func start(_ action: ShortcutAction, in shortcuts: ShortcutsStore) {
        stop()
        self.action = action
        refusal = nil
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return event }
            self.record(event, in: shortcuts)
            return nil
        }
    }

    func stop() {
        if let monitor {
            NSEvent.removeMonitor(monitor)
        }
        monitor = nil
        action = nil
    }

    private func record(_ event: NSEvent, in shortcuts: ShortcutsStore) {
        guard let action else { return }
        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        var modifiers = KeyModifiers()
        if flags.contains(.command) { modifiers.insert(.command) }
        if flags.contains(.shift) { modifiers.insert(.shift) }
        if flags.contains(.option) { modifiers.insert(.option) }
        if flags.contains(.control) { modifiers.insert(.control) }
        // The key as typed without modifiers, so Shift-[ stays "[".
        let characters = event.characters(byApplyingModifiers: [])
        guard
            let result = shortcuts.record(
                keyCode: event.keyCode, characters: characters, modifiers: modifiers, for: action)
        else { return }
        switch result.change {
        case .saved, .cancelled:
            stop()
        default:
            refusal = result.change.message(for: result.shortcut).map { (action, $0) }
        }
    }
}
