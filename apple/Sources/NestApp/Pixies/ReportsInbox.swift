import NestKit
import SwiftUI

/// The pixies' unread warnings and actions at the top of the Pixies list (B42), newest
/// first: the pixie, the report's title, Open (the pixie, its reports read) and Dismiss.
/// Hidden while there are none.
struct ReportsInbox: View {
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        let inbox = shell.reports.inbox
        if !inbox.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 7) {
                    Text(ReportText.inboxTitle)
                    CountBadge(count: inbox.count, urgent: shell.reports.unreadActions() > 0)
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.horizontal, 6)
                ForEach(inbox) { report in
                    ReportEntry(report: report)
                        .transition(
                            .asymmetric(
                                insertion: .opacity,
                                removal: .move(edge: .leading).combined(with: .opacity)))
                }
            }
            .padding(.bottom, 12)
            .animation(reduceMotion ? nil : .smooth(duration: 0.3), value: inbox.map(\.id))
        }
    }
}

private struct ReportEntry: View {
    let report: PixieReport
    @Environment(Shell.self) private var shell

    var body: some View {
        let pixie = shell.pixie(report.pixieID)
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                StatusDot(tone: report.severity.tone)
                if let pixie {
                    SpriteView(mascot: pixie.mascot, color: pixie.color, size: 12)
                }
                Text(pixie?.name ?? "A pixie")
                    .lineLimit(1)
                    .foregroundStyle(Palette.t2)
                Spacer(minLength: 4)
                TimelineView(.periodic(from: .now, by: 60)) { context in
                    Text(PixieActivityText.time(report.createdAt, now: context.date))
                        .monospacedDigit()
                }
                .foregroundStyle(Palette.t3)
            }
            .font(.ui(TypeSize.meta))
            Text(report.title)
                .font(.ui(TypeSize.ui, .medium))
                .foregroundStyle(Palette.t1)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 4) {
                Button("Open") { shell.openReport(report) }
                    .buttonStyle(.nest(.soft, height: 22))
                    .help("Open \(pixie?.name ?? "the pixie") and mark its reports read")
                Button("Dismiss") { shell.dismissReport(report) }
                    .buttonStyle(.nest(.plain, height: 22))
                    .help("Mark this report read")
            }
            .padding(.top, 1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
        .accessibilityElement(children: .contain)
        .accessibilityLabel(
            "\(report.severity.label) from \(pixie?.name ?? "a pixie"): \(report.title)")
    }
}
