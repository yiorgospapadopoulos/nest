import NestKit
import SwiftUI

/// SF Symbols for the mockup's icon set.
enum Icon {
    static let plus = "plus"
    static let search = "magnifyingglass"
    static let mic = "mic"
    static let attach = "paperclip"
    static let send = "arrow.up"
    static let chevron = "chevron.down"
    static let chevronLeft = "chevron.left"
    static let chevronRight = "chevron.right"
    static let close = "xmark"
    static let check = "checkmark"
    static let branch = "arrow.triangle.branch"
    static let folder = "folder"
    static let file = "doc"
    static let terminal = "terminal"
    static let edit = "pencil"
    static let spark = "sparkles"
    static let board = "rectangle.split.3x1"
    static let workspace = "rectangle.split.2x1"
    static let shield = "checkmark.shield"
    static let rightPanel = "sidebar.right"
    static let leftPanel = "sidebar.left"
    static let maximize = "arrow.up.left.and.arrow.down.right"
    static let restore = "arrow.down.right.and.arrow.up.left"
    static let open = "arrow.up.forward.square"
    static let agent = "cpu"
    static let bell = "bell"
    static let goals = "checklist"
    static let question = "questionmark.circle"
    static let plan = "list.bullet.clipboard"
    static let pullRequest = "arrow.triangle.pull"
    static let gear = "gearshape"
    static let more = "ellipsis"
    static let pin = "pin"
    static let archive = "archivebox"
    static let trash = "trash"
    static let code = "chevron.left.forwardslash.chevron.right"
    static let copy = "doc.on.doc"
    static let stop = "stop.fill"
    static let warning = "exclamationmark.triangle"
    static let hook = "bolt"
    static let phone = "iphone"
    static let laptop = "laptopcomputer"
    static let refresh = "arrow.clockwise"
    static let rewind = "arrow.uturn.backward"
    static let fork = "arrow.branch"
    static let globe = "globe"
    static let merge = "arrow.triangle.merge"
    static let server = "server.rack"
    static let diff = "plus.forwardslash.minus"
    static let team = "person.2.fill"
    static let sendAway = "rectangle.portrait.and.arrow.right"

    static func tool(_ kind: ToolSummary.Kind) -> String {
        switch kind {
        case .read: "doc.text"
        case .edit: "pencil"
        case .terminal: "terminal"
        case .search: "magnifyingglass"
        case .agent: "cpu"
        case .web: "globe"
        case .other: "wrench.and.screwdriver"
        }
    }
}

/// A small status dot in the tone's color; hollow marks a missing or skipped result, such as
/// a pull request without checks. No glow and no pulse.
struct StatusDot: View {
    let tone: StatusTone
    var hollow = false
    var size: Double = 6

    var body: some View {
        Circle()
            .fill(hollow ? Color.clear : tone.color)
            .overlay {
                if hollow {
                    Circle().strokeBorder(tone.color, lineWidth: 1.2)
                }
            }
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

/// An expanding ring around a recording button.
struct PulseRing: View {
    let color: Color
    let size: Double

    var body: some View {
        PhaseAnimator([false, true]) { expanded in
            Circle()
                .stroke(color.opacity(expanded ? 0 : 1), lineWidth: expanded ? 0.5 : 3)
                .frame(width: size + (expanded ? 12 : 0), height: size + (expanded ? 12 : 0))
        } animation: { expanded in
            expanded ? .easeOut(duration: DesignTokens.Motion.Duration.pulse) : nil
        }
        .allowsHitTesting(false)
    }
}

/// Status as a dot and a quiet colored word, such as "Needs approval" in a pane header.
struct StatusLabel: View {
    let tone: StatusTone
    let label: String
    var hollow = false
    var showsLabel = true

    var body: some View {
        HStack(spacing: 5) {
            StatusDot(tone: tone, hollow: hollow)
            if showsLabel {
                Text(label).lineLimit(1)
            }
        }
        .font(.ui(TypeSize.meta))
        .foregroundStyle(tone.color)
        .fixedSize()
        .accessibilityElement(children: .combine)
        .accessibilityLabel(label)
    }
}

/// A quiet amber "Stuck" on a chat that looks stuck, with the reason as its tooltip.
struct StuckBadge: View {
    let flag: StuckFlag

    var body: some View {
        Text("Stuck")
            .font(.ui(TypeSize.meta, .medium))
            .foregroundStyle(StatusTone.waiting.color)
            .fixedSize()
            .help(flag.help)
            .accessibilityLabel("Stuck: \(flag.details)")
    }
}

/// A quiet inline label with an optional icon and no fill, such as the branch, or the
/// composer's model, effort and mode.
struct Chip: View {
    var icon: String?
    let text: String
    var mono = false

    var body: some View {
        HStack(spacing: 4) {
            if let icon {
                Image(systemName: icon).font(.system(size: 10, weight: .medium))
            }
            Text(text)
                .font(mono ? .mono(TypeSize.meta) : .ui(TypeSize.button))
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .foregroundStyle(Palette.t2)
        .help(text)
    }
}

/// Inline code or a path as a small soft chip in mono, optionally in the link color.
struct CodeChip: View {
    let text: String
    var link = false

    var body: some View {
        Text(text)
            .font(.mono(TypeSize.meta))
            .foregroundStyle(link ? Palette.link : Palette.t1)
            .lineLimit(1)
            .truncationMode(.middle)
            .padding(.horizontal, 5)
            .padding(.vertical, 1)
            .background(Palette.soft, in: .rounded(Radius.chip))
    }
}

/// The user's round avatar: initials on the selection fill.
struct Avatar: View {
    let name: String
    var size: Double = 20

    var body: some View {
        Text(Initials.of(name))
            .font(.system(size: size * 0.45, weight: .semibold))
            .foregroundStyle(Palette.t1)
            .frame(width: size, height: size)
            .background(Palette.selection, in: Circle())
            .accessibilityHidden(true)
    }
}

/// A count as a plain number: amber when it needs the user, grey otherwise.
struct CountBadge: View {
    let count: Int
    var urgent = false

    var body: some View {
        Text("\(count)")
            .font(.ui(TypeSize.meta))
            .monospacedDigit()
            .foregroundStyle(urgent ? StatusTone.waiting.color : Palette.t3)
    }
}

/// A spinning ring in the running color.
struct Spinner: View {
    var size: Double = 14
    var lineWidth: Double = 2
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(paused: reduceMotion)) { context in
            let angle =
                context.date.timeIntervalSinceReferenceDate.truncatingRemainder(
                    dividingBy: 0.9) / 0.9 * 360
            ZStack {
                Circle().stroke(StatusTone.running.soft, lineWidth: lineWidth)
                Circle()
                    .trim(from: 0, to: reduceMotion ? 0.5 : 0.25)
                    .stroke(StatusTone.running.color, lineWidth: lineWidth)
                    .rotationEffect(.degrees(angle))
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// A thin progress bar: grey on a raised track unless given a color.
struct Meter: View {
    let value: Double
    var height: Double = 3
    var color: Color?

    var body: some View {
        Capsule()
            .fill(Palette.raised)
            .frame(height: height)
            .overlay(alignment: .leading) {
                GeometryReader { geometry in
                    Capsule()
                        .fill(color ?? Palette.t2)
                        .frame(width: geometry.size.width * min(max(value, 0), 1))
                }
            }
            .clipShape(Capsule())
    }
}

/// A small progress ring, as the usage button shows it.
struct ProgressRing: View {
    let value: Double

    var body: some View {
        ZStack {
            Circle().stroke(Palette.divider, lineWidth: 2)
            Circle()
                .trim(from: 0, to: min(max(value, 0), 1))
                .stroke(Palette.t2, lineWidth: 2)
                .rotationEffect(.degrees(-90))
        }
        .frame(width: 12, height: 12)
        .padding(1)
        .accessibilityHidden(true)
    }
}

/// The look's buttons, flat and small: `primary` filled in the accent, `soft` on a soft
/// fill, `plain` text only; `danger` is soft with red text and `destructive` filled red.
struct NestButtonStyle: ButtonStyle {
    enum Kind {
        case primary, soft, plain, danger, destructive
    }

    var kind = Kind.soft
    var height: Double = Metrics.buttonHeight
    var iconOnly = false
    @Environment(\.accentColors) private var accent
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .font(.ui(height > 26 ? TypeSize.ui : TypeSize.button, weight))
                .labelStyle(TightLabelStyle())
                .foregroundStyle(foreground)
                .padding(.horizontal, iconOnly ? 0 : (kind == .plain ? 6 : 9))
                .frame(width: iconOnly ? height : nil, height: height)
                .background(background(hovering: hovering), in: .rounded(Radius.button))
                .contentShape(.rounded(Radius.button))
                .opacity(configuration.isPressed ? 0.75 : isEnabled ? 1 : 0.35)
                .pointerStyle(isEnabled ? .link : nil)
        }
    }

    private var weight: Font.Weight {
        kind == .primary || kind == .destructive ? .medium : .regular
    }

    private var foreground: Color {
        switch kind {
        case .primary: accent.onAccent
        case .soft: Palette.t1
        case .plain: Palette.t2
        case .danger: StatusTone.failed.color
        case .destructive: .white
        }
    }

    private func background(hovering: Bool) -> Color {
        switch kind {
        case .primary: hovering ? accent.accent.opacity(0.85) : accent.accent
        case .soft: hovering ? Palette.selection : Palette.soft
        case .plain: hovering ? Palette.hover : .clear
        case .danger: hovering ? StatusTone.failed.soft : Palette.soft
        case .destructive:
            hovering ? StatusTone.failed.color.opacity(0.85) : StatusTone.failed.color
        }
    }
}

extension ButtonStyle where Self == NestButtonStyle {
    static func nest(
        _ kind: NestButtonStyle.Kind = .soft, height: Double = Metrics.buttonHeight,
        iconOnly: Bool = false
    ) -> NestButtonStyle {
        NestButtonStyle(kind: kind, height: height, iconOnly: iconOnly)
    }
}

/// Icon and title with a 6 point gap.
struct TightLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) {
            configuration.icon.font(.system(size: 11, weight: .medium))
            configuration.title
        }
    }
}

/// Gives its content the pointer's hover state.
struct HoverReader<Content: View>: View {
    @ViewBuilder let content: (Bool) -> Content
    @State private var hovering = false

    var body: some View {
        content(hovering).onHover { hovering = $0 }
    }
}

/// A small grey section label, such as "Running" over the sidebar's running chats, with
/// its count on the right when given one.
struct SectionLabel: View {
    let text: String
    var count: Int?

    var body: some View {
        HStack(spacing: 6) {
            Text(text)
            if let count {
                Spacer(minLength: 0)
                Text("\(count)").monospacedDigit()
            }
        }
        .font(.ui(TypeSize.meta))
        .foregroundStyle(Palette.t3)
    }
}

/// A 1 point line between areas or sections, horizontal by default.
struct Separator: View {
    var axis = Axis.horizontal

    var body: some View {
        Rectangle()
            .fill(Palette.divider)
            .frame(width: axis == .vertical ? 1 : nil, height: axis == .horizontal ? 1 : nil)
            .accessibilityHidden(true)
    }
}

extension View {
    /// A list row's background: the accent's selection when selected, the hover fill while
    /// hovered, nothing otherwise.
    func listRow(selected: Bool = false, radius: Double = Radius.row) -> some View {
        modifier(ListRowBackground(selected: selected, radius: radius))
    }
}

private struct ListRowBackground: ViewModifier {
    let selected: Bool
    let radius: Double
    @Environment(\.accentColors) private var accent

    func body(content: Content) -> some View {
        HoverReader { hovering in
            content.background(
                selected ? accent.selection : hovering ? Palette.hover : .clear,
                in: .rounded(radius))
        }
    }
}

/// Buttons laid out as list rows: primary text, the hover fill while hovered or pressed.
struct RowHoverStyle: ButtonStyle {
    var radius = Radius.row

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(Palette.t1)
                .background(
                    hovering || configuration.isPressed ? Palette.hover : .clear,
                    in: .rounded(radius)
                )
                .pointerStyle(.link)
        }
    }
}
