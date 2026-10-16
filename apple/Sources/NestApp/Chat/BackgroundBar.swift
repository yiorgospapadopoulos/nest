import NestKit
import SwiftUI

/// "N running tasks" just above the composer while any of the chat's subagents or
/// background commands runs (B76); hidden when none does. Clicking it opens the list of
/// running tasks upwards, each with Stop.
struct BackgroundBar: View {
    static let listHeight = 220.0

    let chat: String
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        let summary = shell.activity.background(session: chat)
        let items = summary.runningItems
        if !items.isEmpty {
            let expanded = shell.projectState.expandedBackground.contains(chat)
            let shape = RoundedRectangle.rounded(Radius.card)
            VStack(spacing: 0) {
                if expanded {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 6) {
                            SectionLabel(text: "Running")
                            ForEach(items) { item in
                                BackgroundRow(chat: chat, item: item)
                            }
                        }
                        .accessibilityElement(children: .contain)
                        .accessibilityLabel("Running")
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
                        StatusDot(tone: .running)
                        Text(summary.runningLabel)
                            .font(.ui(TypeSize.ui))
                            .monospacedDigit()
                            .foregroundStyle(Palette.t2)
                            .shimmer(true)
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
                .help(expanded ? "Hide running tasks" : "Show running tasks")
                .accessibilityLabel(summary.runningLabel)
                .accessibilityValue(expanded ? "Expanded" : "Collapsed")
            }
            .background(shape.fill(Palette.soft))
            .clipShape(shape)
            .padding(.horizontal, 12)
            .padding(.bottom, 6)
        }
    }
}

/// Kind icon, name, description and how long it has been running, then Stop.
private struct BackgroundRow: View {
    let chat: String
    let item: BackgroundItem

    var body: some View {
        HStack(spacing: 8) {
            StatusDot(tone: .running)
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
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(item.duration(at: context.date) ?? "")
                    .font(.ui(TypeSize.meta))
                    .monospacedDigit()
                    .foregroundStyle(Palette.t3)
            }
            .fixedSize()
            StopTaskButton(chat: chat, task: item.id)
        }
        .help(item.description.map { "\(item.name): \($0)" } ?? item.name)
    }
}
