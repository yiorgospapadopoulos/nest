import NestKit
import SwiftUI

/// Settings > Usage (B86): what the usage popover shows, at the page's width, then the
/// usage settings.
struct UsagePage: View {
    var body: some View {
        UsagePanel(title: "Limits")
            .padding(.top, 18)
        TopBarSection()
        UsageLimitsSection()
    }
}

/// Which accounts the usage meter at the top right shows, and in which order, on this Mac
/// only (B98): a check per account, in the user's order; a click on the row toggles it, and
/// its grip, or Alt and the arrow keys, move it.
private struct TopBarSection: View {
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion
    @State private var drag: RowDrag?
    @State private var rowHeight = 36.0

    private struct RowDrag {
        let id: String
        let start: Int
        let translation: Double
    }

    var body: some View {
        let settings = shell.settings
        let entries = UsageMeter.entries(shell.model.accounts.accounts, choice: settings.usageMeter)
        let ids = entries.map(\.id)
        SettingsSection(title: "Top bar shows", hint: (Icon.grip, "Drag to reorder")) {
            ForEach(Array(entries.enumerated()), id: \.element.id) { index, entry in
                let dragged = drag?.id == entry.id
                SettingsRow(label: entry.name) {
                    Image(systemName: Icon.grip)
                        .font(.system(size: 10))
                        .foregroundStyle(Palette.t3)
                        .frame(width: 14, height: 20)
                        .contentShape(Rectangle())
                        .pointerStyle(.grabIdle)
                        .gesture(reorder(entry.id, at: index, ids: ids))
                        .accessibilityHidden(true)
                    EngineMark(provider: entry.provider, size: 12)
                        .foregroundStyle(Palette.t2)
                } control: {
                    if !entry.detail.isEmpty {
                        Text(entry.detail)
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                    }
                    SettingsCheckBox(on: entry.shown)
                }
                .background(dragged ? Palette.windowOpaque : .clear)
                .onGeometryChange(for: Double.self) {
                    $0.size.height
                } action: {
                    rowHeight = $0
                }
                .offset(y: offset(of: index, dragged: dragged, count: ids.count))
                .zIndex(dragged ? 1 : 0)
                .animation(
                    dragged || reduceMotion ? nil : .smooth(duration: 0.18),
                    value: drag.map { target(of: $0, count: ids.count) }
                )
                .contentShape(Rectangle())
                .onTapGesture {
                    settings.setUsageMeter(entry.id, shown: !entry.shown, entries: entries)
                }
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(entry.shown ? [.isButton, .isSelected] : .isButton)
                .accessibilityLabel("Show \(entry.name) in the top bar")
                .accessibilityHint("Alt and the arrow keys move it")
                .focusable()
                .focusEffectDisabled()
                .onKeyPress(keys: [.upArrow, .downArrow]) { press in
                    guard press.modifiers.contains(.option) else { return .ignored }
                    let offset = press.key == .upArrow ? -1 : 1
                    settings.orderUsageMeter(UsageMeter.moved(ids, entry.id, by: offset))
                    return .handled
                }
            }
        }
        .task { try? await shell.model.accounts.load() }
    }

    private func target(of drag: RowDrag, count: Int) -> Int {
        TabReorder.target(
            from: drag.start, translation: drag.translation, step: rowHeight, count: count)
    }

    /// The dragged row follows the pointer; the rows it passes slide aside.
    private func offset(of index: Int, dragged: Bool, count: Int) -> Double {
        guard let drag else { return 0 }
        if dragged {
            return drag.translation
        }
        return TabReorder.offset(
            of: index, from: drag.start, to: target(of: drag, count: count), step: rowHeight)
    }

    private func reorder(_ id: String, at index: Int, ids: [String]) -> some Gesture {
        DragGesture(minimumDistance: 2, coordinateSpace: .global)
            .onChanged { value in
                drag = RowDrag(id: id, start: index, translation: value.translation.height)
            }
            .onEnded { value in
                let landing = RowDrag(id: id, start: index, translation: value.translation.height)
                withAnimation(reduceMotion ? nil : .smooth(duration: 0.18)) {
                    shell.settings.orderUsageMeter(
                        UsageMeter.moved(
                            ids, from: index, to: target(of: landing, count: ids.count)))
                    drag = nil
                }
            }
    }
}

/// How often the daemon asks Claude for the limits (D031), and the warning before them.
private struct UsageLimitsSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        let settings = usage.settings
        SettingsSection(title: "Usage limits") {
            SettingsRow(label: "Check limits") {
                DropdownMenu(title: UsageText.refreshInterval(usage.refreshMinutes)) {
                    ForEach(UsageText.refreshChoices, id: \.self) { minutes in
                        Button(UsageText.refreshInterval(minutes)) {
                            change { try await usage.setRefreshMinutes(minutes) }
                        }
                    }
                }
                .disabled(settings == nil)
            }
            SettingsRow(label: "Warn me at") {
                DropdownMenu(
                    title: settings.map { UsageText.warnLevel($0.warnPercent) } ?? "-", width: 100
                ) {
                    ForEach(UsageText.warnChoices, id: \.self) { percent in
                        Button(UsageText.warnLevel(percent)) {
                            change { try await usage.setWarnPercent(percent) }
                        }
                    }
                }
                .disabled(settings == nil)
            }
            SettingsRow(label: "Also as a notification") {
                let on = settings?.warnNotify ?? false
                Switch(isOn: on) { change { try await usage.setWarnNotify(!on) } }
                    .disabled(settings == nil || settings?.warnPercent == nil)
                    .accessibilityLabel("Usage warning as a notification")
            }
        }
        .task { try? await usage.loadSettings() }
    }

    private func change(_ action: @escaping @MainActor () async throws -> Void) {
        shell.settingsChange("Could not change the usage settings", action)
    }
}
