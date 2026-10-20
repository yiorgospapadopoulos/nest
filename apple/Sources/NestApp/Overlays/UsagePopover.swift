import NestKit
import SwiftUI

/// The usage popover (B84): the usage panel at 340 points on the sheet surface.
struct UsagePopover: View {
    /// From the window's right edge to the usage button's: the search field and gaps.
    static let trailingInset = 190.0

    var body: some View {
        UsagePanel(title: "Usage")
            .padding(14)
            .frame(width: 340)
            .sheetSurface()
    }
}

/// Claude's 5 hour and weekly limits, and since B91 those of each other engine signed in
/// under its name, with a Refresh that says when they were reported,
/// then a day, week, month or year of tokens as bars with hover detail, its chats and
/// subagents, and Details, which swaps in the period's breakdown (B84). Shared by the
/// popover and Settings > Usage (B86), at their widths.
struct UsagePanel: View {
    /// The limits' heading.
    let title: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        VStack(alignment: .leading, spacing: 0) {
            if usage.showsDetails {
                UsageBreakdownView()
            } else {
                UsageChart(title: title)
            }
        }
        .font(.ui(TypeSize.ui))
        .monospacedDigit()
        .foregroundStyle(Palette.t1)
        .task { try? await usage.loadPeriod() }
    }
}

/// The limits, the period switch, the bars and the period's totals.
private struct UsageChart: View {
    let title: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        HStack(spacing: 8) {
            Text(title).font(.ui(TypeSize.ui, .semibold))
            Spacer(minLength: 0)
            RefreshControl()
        }
        .frame(height: Metrics.buttonHeight)
        .padding(.bottom, 12)
        ForEach(usage.limitGroups(providers: shell.providers)) { group in
            if let title = group.title {
                Text(title)
                    .font(.ui(TypeSize.meta, .medium))
                    .foregroundStyle(Palette.t3)
                    .padding(.bottom, 6)
            }
            // Claude's 5 hour and weekly windows; another engine's, whichever it has (B91).
            let rows = group.rows
            ForEach(rows) { row in
                LimitRow(title: row.title, window: row.window)
                    .padding(.bottom, row == rows.last ? 14 : 12)
            }
        }
        Separator().padding(.bottom, 12)
        Segmented(
            options: UsageUnit.allCases.map { ($0, $0.title) }, selection: usage.unit,
            fillsWidth: true
        ) { unit in Task { try? await usage.choose(unit) } }
        .padding(.bottom, 8)
        PeriodNavigation()
            .padding(.bottom, 6)
        UsageBars()
        Totals()
            .padding(.top, 10)
        Button {
            usage.showDetails()
        } label: {
            HStack(spacing: 4) {
                Text("Details")
                Image(systemName: Icon.chevronRight).font(.system(size: 9, weight: .semibold))
            }
        }
        .buttonStyle(.nest(.plain))
        .padding(.top, 4)
        .padding(.leading, -8)
        .accessibilityLabel("Details of \(usage.breakdownTitle)")
    }
}

/// Refresh asks Claude at once and says when the limits were last reported; too soon
/// after the last ask, it says when to try again.
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
            TimelineView(.everyMinute) { context in
                Button {
                    Task { await usage.refresh() }
                } label: {
                    Label {
                        Text(usage.refreshTitle)
                            .opacity(usage.limitsAreStale(at: context.date) ? 0.6 : 1)
                    } icon: {
                        if usage.isRefreshing {
                            Fireflies(height: 9)
                        } else {
                            Image(systemName: Icon.refresh)
                        }
                    }
                    .labelStyle(TightLabelStyle())
                }
                .buttonStyle(.nest(.plain))
                .disabled(usage.isRefreshing)
                .help(
                    usage.limitsAreStale(at: context.date)
                        ? "More than 10 minutes old. Ask for the limits now"
                        : "Ask for the limits now")
            }
        }
    }

    @ViewBuilder private func note(_ text: String?) -> some View {
        if let text {
            Text(text)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
        }
    }
}

/// A limit's name and percent, a 3 point bar and when it resets. Every engine's rows look
/// the same (B91): how old the limits are shows on Refresh, not by dimming a row.
private struct LimitRow: View {
    let title: String
    let window: LimitWindow?
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        TimelineView(.everyMinute) { _ in
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(title).foregroundStyle(Palette.t2)
                    Spacer()
                    Text(UsageText.percent(window)).fontWeight(.medium)
                }
                Meter(value: window?.utilization ?? 0, height: 3, color: Palette.t1)
                Text(usage.resetText(window))
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
            }
            .accessibilityElement(children: .combine)
        }
    }
}

/// ‹ the period's title ›; the current period has no next.
private struct PeriodNavigation: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        HStack(spacing: 6) {
            step(Icon.chevronLeft, "Previous") { try await usage.showPrevious() }
            Text(usage.periodTitle)
                .font(.ui(TypeSize.ui, .semibold))
                .frame(maxWidth: .infinity)
            step(Icon.chevronRight, "Next") { try await usage.showNext() }
                .disabled(!usage.canShowNext)
        }
    }

    private func step(
        _ icon: String, _ label: String, _ action: @escaping @MainActor () async throws -> Void
    ) -> some View {
        Button {
            Task { try? await action() }
        } label: {
            Image(systemName: icon).font(.system(size: 10, weight: .semibold))
        }
        .buttonStyle(.nest(.plain, iconOnly: true))
        .accessibilityLabel(label)
    }
}

/// Where the hovered bar sits, for its tooltip.
private struct HoveredBarKey: PreferenceKey {
    static let defaultValue: Anchor<CGRect>? = nil

    static func reduce(value: inout Anchor<CGRect>?, nextValue: () -> Anchor<CGRect>?) {
        value = value ?? nextValue()
    }
}

/// The period's bars on a base line, scaled to the busiest, with their ticks below;
/// hovering a bar shows its detail.
private struct UsageBars: View {
    @Environment(Shell.self) private var shell
    @State private var hovered: Int?

    var body: some View {
        let usage = shell.model.usage
        let bars = usage.bars
        VStack(spacing: 3) {
            HStack(alignment: .bottom, spacing: 2) {
                ForEach(bars) { bar in
                    BarView(bar: bar, hovered: $hovered)
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: UsageStore.barsHeight + 4, alignment: .bottom)
            .padding(.bottom, 4)
            .overlay(alignment: .bottom) { Separator() }
            HStack(spacing: 0) {
                ForEach(Array(usage.ticks.enumerated()), id: \.offset) { index, tick in
                    if index > 0 {
                        Spacer(minLength: 0)
                    }
                    Text(tick)
                }
            }
            .font(.ui(TypeSize.micro))
            .foregroundStyle(Palette.t3)
        }
        .overlayPreferenceValue(HoveredBarKey.self) { anchor in
            GeometryReader { geometry in
                if let anchor, let id = hovered, let tip = bars.first(where: { $0.id == id })?.tip {
                    let rect = geometry[anchor]
                    Text(tip)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t1)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .sheetSurface(radius: Radius.card)
                        .fixedSize()
                        .position(
                            x: min(max(rect.midX, 100), geometry.size.width - 100),
                            y: -14
                        )
                        .allowsHitTesting(false)
                }
            }
        }
    }
}

private struct BarView: View {
    let bar: UsageBarCell
    @Binding var hovered: Int?

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 1)
        shape
            .fill(fill)
            .frame(maxWidth: .infinity)
            .frame(height: bar.height)
            .opacity(hovered == nil || hovered == bar.id ? 1 : 0.55)
            // The whole column answers the pointer, not only the bar.
            .frame(maxHeight: .infinity, alignment: .bottom)
            .contentShape(Rectangle())
            .onHover { inside in
                if inside && bar.tip != nil {
                    hovered = bar.id
                } else if hovered == bar.id {
                    hovered = nil
                }
            }
            .anchorPreference(key: HoveredBarKey.self, value: .bounds) { anchor in
                hovered == bar.id ? anchor : nil
            }
            .accessibilityElement()
            .accessibilityLabel(bar.tip ?? "Not yet")
    }

    private var fill: Color {
        if bar.isFuture {
            return .clear
        }
        return bar.height > 1 ? Palette.t2 : Palette.divider
    }
}

/// Chats, Subagents and the total with its number of chats.
private struct Totals: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        VStack(spacing: 0) {
            line("Chats", usage.chatsText)
            Separator()
            line("Subagents", usage.subagentsText)
            Rectangle().fill(Palette.t3.opacity(0.5)).frame(height: 1)
            line(usage.totalLabel, usage.totalText, total: true)
        }
    }

    private func line(_ label: String, _ value: String, total: Bool = false) -> some View {
        HStack {
            Text(label).foregroundStyle(total ? Palette.t1 : Palette.t2)
            Spacer()
            Text(value)
        }
        .fontWeight(total ? .semibold : .medium)
        .padding(.vertical, total ? 6 : 5)
        .accessibilityElement(children: .combine)
    }
}

/// The shown period's tokens by engine (B91), by who, by kind and by project, with the
/// usage checks counted apart; ‹ goes back to the chart.
private struct UsageBreakdownView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        let breakdown = usage.breakdown(providers: shell.providers)
        HStack(spacing: 6) {
            Button {
                usage.hideDetails()
            } label: {
                Image(systemName: Icon.chevronLeft).font(.system(size: 10, weight: .semibold))
            }
            .buttonStyle(.nest(.plain, iconOnly: true))
            .accessibilityLabel("Back")
            Text(usage.breakdownTitle).font(.ui(TypeSize.ui, .semibold))
            Spacer(minLength: 0)
            Text(breakdown?.total ?? "-").font(.ui(TypeSize.ui, .semibold))
        }
        .frame(height: Metrics.buttonHeight)
        .padding(.leading, -6)
        .padding(.bottom, 12)
        if let breakdown {
            if !breakdown.engines.isEmpty {
                heading("By engine")
                ShareRows(rows: breakdown.engines).padding(.bottom, 14)
            }
            heading("By who")
            ShareRows(rows: breakdown.who).padding(.bottom, 14)
            heading("By kind")
            ShareRows(rows: breakdown.kinds).padding(.bottom, 14)
            if !breakdown.projects.isEmpty {
                heading("By project")
                VStack(alignment: .leading, spacing: 7) {
                    ForEach(breakdown.projects) { project in
                        VStack(alignment: .leading, spacing: 3) {
                            HStack {
                                Text(project.name).lineLimit(1).truncationMode(.middle)
                                Spacer()
                                Text(project.value)
                            }
                            Meter(value: project.fraction, height: 3, color: Palette.t2)
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
            }
            if let probes = breakdown.probes {
                Text(probes)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .padding(.top, 14)
            }
        } else {
            Text("Loading").foregroundStyle(Palette.t3)
        }
    }

    private func heading(_ text: String) -> some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .padding(.bottom, 4)
    }
}

/// Label, tokens and share, one line each.
private struct ShareRows: View {
    let rows: [UsageBreakdown.Row]

    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                HStack(spacing: 10) {
                    Text(row.label)
                    Spacer(minLength: 0)
                    Text(row.value).frame(width: 60, alignment: .trailing)
                    Text(row.share)
                        .foregroundStyle(Palette.t3)
                        .frame(width: 48, alignment: .trailing)
                }
                .padding(.vertical, 5)
                .overlay(alignment: .top) {
                    if index > 0 {
                        Separator()
                    }
                }
                .accessibilityElement(children: .combine)
            }
        }
    }
}
