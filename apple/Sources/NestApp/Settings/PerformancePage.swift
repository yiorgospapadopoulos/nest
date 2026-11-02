import NestKit
import SwiftUI

/// Settings > Performance (B115): the last run and its buttons, four cards, the main
/// sections with this run's bars against the previous run's, Advanced (closed each time
/// the page opens) and what changed. The daemon writes every label and number.
struct PerformancePage: View {
    @Environment(Shell.self) private var shell
    @State private var advancedOpen = false

    var body: some View {
        let store = shell.model.performance
        VStack(alignment: .leading, spacing: 0) {
            PerfHeader()
            if let failure = store.failure {
                SettingsFailure(text: failure)
            }
            switch store.state {
            case .loading:
                Fireflies().padding(.vertical, 24)
            case .neverRun, .running, .finished:
                if let view = store.view {
                    content(view, store: store)
                }
            }
        }
        .task {
            if store.measureMac == nil {
                store.measureMac = { [weak shell] in
                    guard let shell else { return [:] }
                    return try await MacPerfProbe.measure(shell)
                }
            }
            await store.load()
        }
    }

    @ViewBuilder private func content(_ view: PerfView, store: PerformanceStore) -> some View {
        if store.state == .neverRun {
            Text("Nothing measured yet. Run all measures every section on the daemon and this Mac.")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 18)
        }
        if !view.cards.isEmpty {
            PerfCards(cards: view.cards).padding(.top, 18)
        }
        if store.state != .neverRun {
            PerfLegend().padding(.top, 18)
        }
        ForEach(store.mainSections) { section in
            PerfSectionView(section: section)
        }
        let advanced = store.advancedSections
        if !advanced.isEmpty {
            AdvancedFold(open: $advancedOpen)
            if advancedOpen {
                ForEach(advanced) { section in
                    PerfSectionView(section: section)
                }
            }
        }
        if store.state != .neverRun {
            PerfChanges(changes: view.changes)
        }
    }
}

/// "Last run today 10:58 · 1 min 42 s", Clear old runs and Run all.
private struct PerfHeader: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.performance
        HStack(spacing: 8) {
            TimelineView(.periodic(from: .now, by: 60)) { context in
                Text(
                    PerfText.header(
                        store.view, measuringMac: store.measuringMac, now: context.date)
                )
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .monospacedDigit()
            }
            Spacer(minLength: 8)
            Button("Clear old runs") {
                Task { await store.clearOldRuns() }
            }
            .buttonStyle(.nest())
            .disabled(store.isRunning || (store.view?.runs ?? 0) == 0)
            Button {
                Task { await store.runAll() }
            } label: {
                Text(store.isRunning ? "Running" : "Run all")
            }
            .buttonStyle(.nest(.primary))
            .disabled(store.isRunning || store.view == nil)
        }
        .padding(.top, 16)
    }
}

// MARK: Cards

/// The four numbers that matter most, two by two.
private struct PerfCards: View {
    let cards: [PerfMetric]

    var body: some View {
        Grid(horizontalSpacing: 10, verticalSpacing: 10) {
            ForEach(Array(stride(from: 0, to: cards.count, by: 2)), id: \.self) { index in
                GridRow {
                    PerfCard(metric: cards[index])
                    if index + 1 < cards.count {
                        PerfCard(metric: cards[index + 1])
                    } else {
                        Color.clear.gridCellUnsizedAxes([.horizontal, .vertical])
                    }
                }
            }
        }
    }
}

private struct PerfCard: View {
    let metric: PerfMetric

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(metric.label)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t2)
                .lineLimit(1)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(metric.text)
                    .font(.ui(24, .semibold))
                    .monospacedDigit()
                if let change = metric.change {
                    ChangeText(change: change)
                }
                Spacer(minLength: 0)
                if let sub = metric.sub {
                    Text(sub)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                }
            }
            ForEach(Array((metric.parts ?? []).prefix(4).enumerated()), id: \.offset) { _, part in
                HStack {
                    Text(part.label).foregroundStyle(Palette.t2)
                    Spacer(minLength: 8)
                    Text(part.text).monospacedDigit()
                }
                .font(.ui(TypeSize.meta))
                .lineLimit(1)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .softFill()
        .accessibilityElement(children: .combine)
    }
}

/// The two bar colours.
private struct PerfLegend: View {
    @Environment(\.accentColors) private var accent

    var body: some View {
        HStack(spacing: 14) {
            key(PerfColors.previous, "Previous run")
            key(accent.fill, "This run")
        }
        .font(.ui(TypeSize.meta))
        .foregroundStyle(Palette.t2)
        .accessibilityElement(children: .combine)
    }

    private func key(_ color: Color, _ title: String) -> some View {
        HStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 8, height: 8)
            Text(title)
        }
    }
}

// MARK: Sections

/// A section's title and Run, then its card: the day bars if it has a series, each
/// metric's row, its error or that it has not run, and its note under the card.
private struct PerfSectionView: View {
    let section: PerfSection
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.performance
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text(section.title)
                    .font(.ui(11, .semibold))
                    .foregroundStyle(Palette.t2)
                if section.live {
                    Image(systemName: "bolt")
                        .font(.system(size: 9))
                        .foregroundStyle(Palette.t3)
                        .help("A run uses a little of your Claude usage")
                        .accessibilityLabel("Uses your Claude usage")
                }
                Spacer(minLength: 8)
                if store.isRunning(section) {
                    Fireflies(height: 9)
                        .accessibilityLabel("Running")
                } else if section.runner != .unknown {
                    Button {
                        Task { await store.run(section) }
                    } label: {
                        Label("Run", systemImage: Icon.play)
                    }
                    .buttonStyle(.nest(.plain, height: 22))
                    .disabled(!store.canRun(section))
                    .accessibilityLabel("Run \(section.title)")
                }
            }
            .frame(minHeight: 22)
            VStack(alignment: .leading, spacing: 0) {
                if let series = section.series, section.ranAt != nil {
                    DayBars(series: series)
                }
                if let error = section.error {
                    Text(error)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(StatusTone.failed.color)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                } else if section.ranAt == nil && !store.isRunning(section) {
                    Text("Not run yet")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .padding(14)
                }
                if !section.metrics.isEmpty && section.ranAt != nil {
                    if section.series != nil {
                        PlainRows(metrics: section.metrics)
                    } else {
                        CompareRows(metrics: section.metrics)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .softFill()
            if let note = section.note {
                Text(note)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 4)
            }
        }
        .padding(.top, 18)
    }
}

/// Label with its quiet word, the previous and this run's bars, the value and the change.
private struct CompareRows: View {
    let metrics: [PerfMetric]
    @Environment(\.accentColors) private var accent

    var body: some View {
        let bars = PerfBars.scale(metrics)
        Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 10) {
            ForEach(metrics) { metric in
                GridRow {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(metric.label)
                        if let sub = metric.sub {
                            Text(sub)
                                .font(.ui(TypeSize.meta))
                                .foregroundStyle(Palette.t3)
                        }
                    }
                    .lineLimit(1)
                    .frame(width: 200, alignment: .leading)
                    let bar = bars[metric.id]
                    VStack(alignment: .leading, spacing: 3) {
                        Bar(share: bar?.previous, color: PerfColors.previous)
                        Bar(share: bar?.current, color: accent.fill)
                    }
                    .accessibilityHidden(true)
                    Text(metric.text)
                        .monospacedDigit()
                        .lineLimit(1)
                        .frame(minWidth: 64, alignment: .trailing)
                        .gridColumnAlignment(.trailing)
                        .help(metric.previousText.map { "Previous run \($0)" } ?? metric.text)
                    Group {
                        if let change = metric.change {
                            ChangeText(change: change)
                        } else {
                            Text("")
                        }
                    }
                    .frame(minWidth: 56, alignment: .trailing)
                    .gridColumnAlignment(.trailing)
                }
                .font(.ui(TypeSize.ui))
                .accessibilityElement(children: .combine)
            }
        }
        .padding(14)
    }
}

/// Rows without bars, under a section's day bars.
private struct PlainRows: View {
    let metrics: [PerfMetric]

    var body: some View {
        VStack(spacing: 0) {
            ForEach(metrics) { metric in
                HStack(spacing: 12) {
                    Text(metric.label)
                    Spacer(minLength: 8)
                    Text(metric.text).monospacedDigit()
                    if let change = metric.change {
                        ChangeText(change: change).frame(minWidth: 56, alignment: .trailing)
                    }
                }
                .font(.ui(TypeSize.ui))
                .padding(.horizontal, 14)
                .padding(.vertical, 9)
                .overlay(alignment: .top) { Separator() }
                .accessibilityElement(children: .combine)
            }
        }
    }
}

/// One bar on its track; no value draws only the track.
private struct Bar: View {
    let share: Double?
    let color: Color

    var body: some View {
        GeometryReader { geometry in
            RoundedRectangle(cornerRadius: 3)
                .fill(color)
                .frame(width: geometry.size.width * (share ?? 0))
        }
        .frame(height: 7)
    }
}

/// A day series as bars, tallest day full height, with the days' values on hover.
private struct DayBars: View {
    let series: PerfSeries
    @Environment(\.accentColors) private var accent

    var body: some View {
        let shares = PerfBars.days(series)
        HStack(alignment: .bottom, spacing: 4) {
            ForEach(Array(series.points.enumerated()), id: \.offset) { index, point in
                RoundedRectangle(cornerRadius: 2)
                    .fill(accent.fill.opacity(0.55))
                    .frame(maxWidth: .infinity)
                    .frame(height: max(2, 48 * shares[index]))
                    .help("\(point.day): \(Int(point.value.rounded()))")
            }
        }
        .frame(height: 48, alignment: .bottom)
        .padding(.horizontal, 14)
        .padding(.top, 14)
        .padding(.bottom, 10)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(series.label)
    }
}

/// "▼ 25%" in its tone's colour.
private struct ChangeText: View {
    let change: PerfChangeMark

    var body: some View {
        Text(change.text)
            .font(.ui(TypeSize.ui))
            .monospacedDigit()
            .foregroundStyle(PerfColors.tone(change.tone))
            .lineLimit(1)
    }
}

enum PerfColors {
    static let previous = Palette.t3.opacity(0.45)

    static func tone(_ tone: PerfTone) -> Color {
        switch tone {
        case .better: StatusTone.review.color
        case .worse: StatusTone.failed.color
        case .same, .unknown: Palette.t3
        }
    }
}

// MARK: Advanced and changes

private struct AdvancedFold: View {
    @Binding var open: Bool

    var body: some View {
        Button {
            withAnimation(.smooth(duration: 0.2)) { open.toggle() }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: Icon.chevronRight)
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(Palette.t3)
                    .rotationEffect(.degrees(open ? 90 : 0))
                    .frame(width: 10)
                Text("Advanced").font(.ui(TypeSize.ui, .medium))
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 14)
            .frame(height: 38)
            .contentShape(Rectangle())
            .softFill()
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .accessibilityValue(open ? "Expanded" : "Collapsed")
        .padding(.top, 18)
    }
}

/// What changed since the previous run, worst first, as the daemon tells it.
private struct PerfChanges: View {
    let changes: [PerfChange]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("What changed")
                .font(.ui(11, .semibold))
                .foregroundStyle(Palette.t2)
                .frame(minHeight: 22)
            VStack(alignment: .leading, spacing: 0) {
                if changes.isEmpty {
                    Text("Nothing changed much since the previous run")
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t3)
                        .padding(14)
                }
                ForEach(Array(changes.enumerated()), id: \.offset) { index, change in
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Circle()
                            .fill(PerfColors.tone(change.tone))
                            .frame(width: 6, height: 6)
                            .alignmentGuide(.firstTextBaseline) { $0[.bottom] }
                        Text(change.text)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                        Spacer(minLength: 0)
                    }
                    .font(.ui(TypeSize.ui))
                    .padding(.horizontal, 14)
                    .padding(.vertical, 9)
                    .overlay(alignment: .top) {
                        if index > 0 {
                            Separator()
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .softFill()
        }
        .padding(.top, 18)
    }
}
