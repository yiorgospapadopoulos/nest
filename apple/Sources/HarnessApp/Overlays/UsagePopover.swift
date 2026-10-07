import HarnessKit
import SwiftUI

/// The usage popover: Claude's 5 hour and weekly limits with when they were reported and a
/// Refresh, this month's sessions and tokens, and a daily token calendar with month
/// navigation and hover detail.
struct UsagePopover: View {
    /// From the window's right edge to the usage button's: the search field and gaps.
    static let trailingInset = 190.0

    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        let usage = shell.model.usage
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text("USAGE")
                    .font(.ui(TypeSize.small, .bold))
                    .tracking(0.7)
                    .foregroundStyle(Palette.t3)
                Spacer(minLength: 0)
                RefreshControl()
            }
            .frame(height: 24)
            .padding(.bottom, 8)
            LimitRow(title: "5 hour window", window: usage.limits?.fiveHour)
            LimitRow(title: "Weekly", window: usage.limits?.sevenDay)
            Text("This month")
                .font(.ui(TypeSize.small, .semibold))
                .padding(.top, 2)
            HStack(spacing: 6) {
                Total(value: "\(usage.totalSessions)", label: "Sessions")
                Total(value: UsageText.tokens(usage.totalTokens), label: "Total tokens")
            }
            .padding(.top, 6)
            .padding(.bottom, 12)
            UsageCalendar()
                .padding(.bottom, 10)
            Text(footnote(probes: usage.probesText))
                .font(.ui(TypeSize.label))
                .foregroundStyle(Palette.t3)
                .lineSpacing(1.5)
                .fixedSize(horizontal: false, vertical: true)
        }
        .foregroundStyle(Palette.t1)
        .padding(14)
        .frame(width: 360)
        .sheetGlass(radius: glass.radius.panel)
        .shadow(color: glass.shadow, radius: 24, y: 14)
        .task { try? await usage.loadMonth() }
    }

    private func footnote(probes: String?) -> String {
        let text =
            "Claude reports the 5 hour and weekly limits; harness asks again every few minutes "
            + "while it is on screen. Monthly and daily figures are counted by harness."
        return probes.map { "\(text) \($0)" } ?? text
    }
}

/// Refresh asks Claude at once; too soon after the last ask, it says when to try again.
private struct RefreshControl: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        HStack(spacing: 6) {
            // Ticks each second only while counting down to the next allowed refresh.
            if usage.retryAt.map({ $0 > .now }) ?? false {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    note(usage.refreshNote(at: context.date))
                }
            } else {
                note(usage.refreshNote(at: .now))
            }
            Button {
                Task { await usage.refresh() }
            } label: {
                Label {
                    Text("Refresh")
                } icon: {
                    if usage.isRefreshing {
                        ProgressView().controlSize(.small).scaleEffect(0.6).frame(
                            width: 12, height: 12)
                    } else {
                        Image(systemName: Icon.refresh)
                    }
                }
            }
            .buttonStyle(.harness(.ghost, height: 24))
            .disabled(usage.isRefreshing)
            .help("Ask Claude for the limits now")
        }
    }

    @ViewBuilder private func note(_ text: String?) -> some View {
        if let text {
            Text(text)
                .font(.ui(TypeSize.caption))
                .monospacedDigit()
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
        }
    }
}

private struct LimitRow: View {
    let title: String
    let window: LimitWindow?
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        TimelineView(.everyMinute) { context in
            let stale = UsageText.isStale(window, now: context.date)
            VStack(alignment: .leading, spacing: 5) {
                HStack {
                    Text(title).foregroundStyle(Palette.t2)
                    Spacer()
                    Text(UsageText.percent(window))
                        .fontWeight(.bold)
                        .opacity(stale ? 0.5 : 1)
                }
                .font(.ui(TypeSize.callout))
                Meter(value: window?.utilization ?? 0, height: 6)
                    .opacity(stale ? 0.5 : 1)
                HStack {
                    Text(usage.resetText(window))
                    Spacer()
                    if let asOf = usage.asOfText(window) {
                        Text(asOf)
                            .monospacedDigit()
                            .opacity(stale ? 0.6 : 1)
                            .help(
                                stale ? "More than 10 minutes old" : "When Claude last reported it")
                    }
                }
                .font(.ui(TypeSize.caption))
                .foregroundStyle(Palette.t3)
            }
            .padding(.bottom, 12)
            .accessibilityElement(children: .combine)
        }
    }
}

private struct Total: View {
    let value: String
    let label: String

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(value).font(.ui(TypeSize.headline, .bold))
            Text(label).font(.ui(10.5)).foregroundStyle(Palette.t3)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.fill, in: RoundedRectangle(cornerRadius: 10))
    }
}

/// Where the hovered day sits, for its tooltip.
private struct HoveredDayKey: PreferenceKey {
    static let defaultValue: Anchor<CGRect>? = nil

    static func reduce(value: inout Anchor<CGRect>?, nextValue: () -> Anchor<CGRect>?) {
        value = value ?? nextValue()
    }
}

/// The month's days, Monday first, shaded by tokens; hovering a day shows its detail.
private struct UsageCalendar: View {
    @Environment(Shell.self) private var shell
    @State private var hovered: CalendarDay?

    var body: some View {
        let usage = shell.model.usage
        let cells = usage.cells
        let columns = Array(repeating: GridItem(.flexible(), spacing: 3), count: 7)
        VStack(spacing: 6) {
            HStack(spacing: 6) {
                navigation(Icon.chevronLeft, "Previous month") {
                    try await usage.showPreviousMonth()
                }
                Text(usage.monthTitle)
                    .font(.ui(TypeSize.body, .bold))
                    .frame(maxWidth: .infinity)
                navigation(Icon.chevronRight, "Next month") { try await usage.showNextMonth() }
                    .disabled(!usage.canShowNextMonth)
            }
            LazyVGrid(columns: columns, spacing: 3) {
                ForEach(UsageText.weekdayHeads, id: \.self) { head in
                    Text(head)
                        .font(.ui(TypeSize.micro, .semibold))
                        .foregroundStyle(Palette.t3)
                        .padding(.bottom, 2)
                }
                ForEach(Array(cells.enumerated()), id: \.offset) { _, cell in
                    if let cell {
                        DayCell(cell: cell, peak: usage.peakDayTokens, hovered: $hovered)
                    } else {
                        Color.clear.frame(height: 40)
                    }
                }
            }
            .frame(minHeight: 40 * 5 + 30, alignment: .top)
        }
        .overlayPreferenceValue(HoveredDayKey.self) { anchor in
            GeometryReader { geometry in
                if let anchor, let day = hovered,
                    let cell = cells.compactMap({ $0 }).first(where: { $0.day == day })
                {
                    let rect = geometry[anchor]
                    let below = rect.minY < 90
                    DayTip(detail: usage.detail(of: cell))
                        .fixedSize()
                        .position(
                            x: min(max(rect.midX, 70), geometry.size.width - 70),
                            y: below ? rect.maxY + 24 : rect.minY - 24
                        )
                        .allowsHitTesting(false)
                }
            }
        }
    }

    private func navigation(
        _ icon: String, _ label: String, _ action: @escaping @MainActor () async throws -> Void
    ) -> some View {
        Button {
            Task { try? await action() }
        } label: {
            Image(systemName: icon).font(.system(size: 11, weight: .semibold))
        }
        .buttonStyle(.harness(.ghost, height: 24, iconOnly: true))
        .accessibilityLabel(label)
    }
}

private struct DayCell: View {
    let cell: UsageDayCell
    let peak: Int
    @Binding var hovered: CalendarDay?
    @Environment(\.accentColors) private var accent

    var body: some View {
        let shade = UsageText.shade(tokens: cell.tokens, peak: peak)
        let strong = UsageText.isStrong(shade: shade)
        let shape = RoundedRectangle(cornerRadius: 8, style: .continuous)
        VStack(alignment: .leading, spacing: 0) {
            Text("\(cell.day.day)")
                .font(.ui(TypeSize.micro))
                .foregroundStyle(strong ? accent.onAccent : cell.isFuture ? Palette.t3 : Palette.t2)
            Spacer(minLength: 0)
            if cell.tokens > 0 {
                Text(UsageText.tokens(cell.tokens))
                    .font(.ui(TypeSize.micro, .semibold))
                    .monospacedDigit()
                    .foregroundStyle(strong ? accent.onAccent : Palette.t1)
            }
        }
        .padding(.horizontal, 5)
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, minHeight: 40, maxHeight: 40, alignment: .topLeading)
        .background {
            if cell.isFuture {
                shape.strokeBorder(Palette.hair)
            } else {
                shape.fill(Palette.fill).overlay(shape.fill(accent.accent.opacity(shade)))
            }
        }
        .overlay {
            if cell.isToday {
                shape.strokeBorder(Palette.t1, lineWidth: 1.5)
            }
        }
        .contentShape(shape)
        .onHover { inside in
            if inside && !cell.isFuture {
                hovered = cell.day
            } else if hovered == cell.day {
                hovered = nil
            }
        }
        .anchorPreference(key: HoveredDayKey.self, value: .bounds) { anchor in
            hovered == cell.day ? anchor : nil
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(cell.day.day): \(UsageText.tokens(cell.tokens)) tokens")
    }
}

private struct DayTip: View {
    let detail: (title: String, detail: String)
    @Environment(\.glass) private var glass

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(detail.title).font(.ui(TypeSize.label, .semibold)).foregroundStyle(Palette.t1)
            Text(detail.detail).font(.ui(TypeSize.caption)).foregroundStyle(Palette.t2)
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 6)
        .sheetGlass(radius: min(glass.radius.item, 9))
    }
}
