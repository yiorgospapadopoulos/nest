import HarnessKit
import SwiftUI

/// "N running · M completed" just above the composer, like Claude Code: the subagents and
/// background commands of the current exchange (since the user's latest message), plus
/// any earlier one still at work. Clicking it opens the Running and Completed lists
/// upwards.
struct BackgroundBar: View {
    static let listHeight = 220.0

    let chat: String
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        let all = shell.activity.background(session: chat)
        let summary = shell.model.transcripts.existing(chat)?.exchange(of: all) ?? all
        if !summary.isEmpty {
            let expanded = shell.projectState.expandedBackground.contains(chat)
            let shape = RoundedRectangle.rounded(Radius.card)
            VStack(spacing: 0) {
                if expanded {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 10) {
                            BackgroundSection(title: "Running", items: summary.runningItems)
                            BackgroundSection(title: "Completed", items: summary.finishedItems)
                        }
                        .padding(EdgeInsets(top: 10, leading: 12, bottom: 8, trailing: 12))
                    }
                    .scrollIndicators(.never)
                    .frame(maxHeight: Self.listHeight)
                    .fixedSize(horizontal: false, vertical: true)
                    .transition(reduceMotion ? .opacity : .opacity.combined(with: .offset(y: 12)))
                    Rectangle().fill(Palette.divider).frame(height: 1)
                }
                Button {
                    shell.update { $0.toggleBackground(chat) }
                } label: {
                    HStack(spacing: 8) {
                        StatusDot(tone: summary.running > 0 ? .running : .done)
                        Text(summary.label)
                            .font(.ui(TypeSize.ui))
                            .monospacedDigit()
                            .foregroundStyle(Palette.t2)
                            .shimmer(summary.running > 0)
                        Spacer(minLength: 4)
                        Image(systemName: Icon.chevron)
                            .font(.system(size: 8, weight: .medium))
                            .foregroundStyle(Palette.t3)
                            .rotationEffect(.degrees(expanded ? 0 : 180))
                    }
                    .padding(.horizontal, 12)
                    .frame(height: 28)
                    .contentShape(Rectangle())
                }
                .buttonStyle(RowHoverStyle(radius: Radius.card))
                .help(expanded ? "Hide background tasks" : "Show background tasks")
                .accessibilityLabel(summary.label)
                .accessibilityValue(expanded ? "Expanded" : "Collapsed")
            }
            .background(shape.fill(Palette.soft))
            .clipShape(shape)
            .padding(.horizontal, 12)
            .padding(.bottom, 6)
        }
    }
}

/// A heading and its items; nothing when there are none.
private struct BackgroundSection: View {
    let title: String
    let items: [BackgroundItem]

    var body: some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                SectionLabel(text: title)
                ForEach(items) { item in
                    BackgroundRow(item: item)
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel(title)
        }
    }
}

/// Status, kind icon, name, description and how long it ran.
private struct BackgroundRow: View {
    let item: BackgroundItem

    var body: some View {
        HStack(spacing: 8) {
            StatusDot(tone: tone)
            Image(systemName: item.kind == .bash ? Icon.terminal : Icon.agent)
                .font(.system(size: 10))
                .foregroundStyle(Palette.t3)
                .frame(width: 12)
            Text(item.name)
                .font(.ui(TypeSize.ui, .medium))
                .foregroundStyle(Palette.t1)
                .lineLimit(1)
                .layoutPriority(1)
            Text(item.description ?? "")
                .font(.mono(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            Group {
                if item.isRunning {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        duration(at: context.date)
                    }
                } else {
                    duration(at: .now)
                }
            }
            .fixedSize()
        }
        .help(item.description.map { "\(item.name): \($0)" } ?? item.name)
    }

    private func duration(at now: Date) -> some View {
        Text(item.duration(at: now) ?? statusText)
            .font(.ui(TypeSize.meta))
            .monospacedDigit()
            .foregroundStyle(Palette.t3)
    }

    private var tone: StatusTone {
        switch item.status {
        case .running: .running
        case .failed: .failed
        default: .done
        }
    }

    private var statusText: String {
        switch item.status {
        case .running: "Running"
        case .done: "Done"
        case .failed: "Failed"
        case .unknown: ""
        }
    }
}
