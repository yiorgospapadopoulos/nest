import HarnessKit
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
    static let phone = "iphone"
    static let laptop = "laptopcomputer"
    static let refresh = "arrow.clockwise"
    static let rewind = "arrow.uturn.backward"
    static let globe = "globe"
    static let merge = "arrow.triangle.merge"
    static let server = "server.rack"

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

/// A status dot; idle is a hollow ring and running pulses.
struct StatusDot: View {
    let tone: StatusTone
    var hollow = false
    var size: Double = 8
    var pulses = true
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        Circle()
            .fill(hollow ? Color.clear : tone.color)
            .overlay {
                if hollow {
                    Circle().strokeBorder(tone.color, lineWidth: 1.5)
                }
            }
            .frame(width: size, height: size)
            .background {
                if tone == .running && pulses && !reduceMotion {
                    PulseRing(color: Palette.runningRing, size: size)
                }
            }
            .accessibilityHidden(true)
    }
}

/// The running dot's expanding ring.
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

/// A status capsule: dot and label on the tone's soft fill.
struct StatusPill: View {
    let tone: StatusTone
    let label: String
    var hollow = false
    var showsLabel = true
    @Environment(\.glass) private var glass

    var body: some View {
        HStack(spacing: 6) {
            StatusDot(tone: tone, hollow: hollow)
            if showsLabel {
                Text(label).lineLimit(1)
            }
        }
        .font(.ui(TypeSize.label, .semibold))
        .foregroundStyle(tone.textColor)
        .padding(.leading, 8)
        .padding(.trailing, showsLabel ? 9 : 7)
        .frame(height: 22)
        .background(tone.soft, in: glass.control)
        .fixedSize()
    }
}

/// An amber "Stuck" capsule on a chat that looks stuck, with the reason as its tooltip.
struct StuckBadge: View {
    let flag: StuckFlag

    var body: some View {
        Text("Stuck")
            .font(.ui(TypeSize.caption, .bold))
            .foregroundStyle(Palette.onWaiting)
            .padding(.horizontal, 6)
            .frame(height: 16)
            .background(StatusTone.waiting.color, in: Capsule())
            .fixedSize()
            .help(flag.help)
            .accessibilityLabel("Stuck: \(flag.details)")
    }
}

/// A small rounded chip such as the branch name.
struct Chip: View {
    let icon: String
    let text: String
    var mono = false
    @Environment(\.glass) private var glass

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: icon).font(.system(size: 10, weight: .medium))
            Text(text)
                .font(mono ? .mono(10.5) : .ui(TypeSize.label))
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .foregroundStyle(Palette.t2)
        .padding(.horizontal, 8)
        .frame(height: 22)
        .background(Palette.fill, in: glass.rounded(glass.radius.small))
        .help(text)
    }
}

/// A project's colored mark with its initials.
struct ProjectMarkView: View {
    let name: String
    var size: Double = 18

    static let colors: [Color] = [
        Color(red: 0.549, green: 0.482, blue: 0.404),
        Color(red: 0.431, green: 0.541, blue: 0.420),
        Color(red: 0.365, green: 0.498, blue: 0.608),
        Color(red: 0.412, green: 0.451, blue: 0.498),
    ]

    var body: some View {
        let color = Self.colors[ProjectMark.colorIndex(for: name, count: Self.colors.count)]
        Text(Initials.of(name))
            .font(.system(size: size * 0.55, weight: .heavy))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(color, in: RoundedRectangle(cornerRadius: size / 3, style: .continuous))
            .overlay(alignment: .top) {
                RoundedRectangle(cornerRadius: size / 3, style: .continuous)
                    .stroke(.white.opacity(0.35), lineWidth: 0.5)
                    .mask(alignment: .top) { Rectangle().frame(height: 1.5) }
            }
            .accessibilityHidden(true)
    }
}

/// The user's round avatar.
struct Avatar: View {
    let name: String
    var size: Double = 30

    var body: some View {
        Text(Initials.of(name))
            .font(.system(size: size * 0.37, weight: .bold))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(Color(red: 0.482, green: 0.427, blue: 0.376), in: Circle())
            .accessibilityHidden(true)
    }
}

/// A count capsule; amber when it needs the user.
struct CountBadge: View {
    let count: Int
    var urgent = false
    var size: Double = 20

    var body: some View {
        Text("\(count)")
            .font(.system(size: size >= 20 ? 11 : 10, weight: urgent ? .heavy : .bold))
            .monospacedDigit()
            .foregroundStyle(urgent ? Palette.onWaiting : Palette.t2)
            .padding(.horizontal, size >= 20 ? 6 : 4)
            .frame(minWidth: size, minHeight: size - 2, maxHeight: size - 2)
            .background(urgent ? StatusTone.waiting.color : Palette.fill2, in: Capsule())
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

/// A thin progress bar.
struct Meter: View {
    let value: Double
    var height: Double = 4
    var color: Color?
    @Environment(\.accentColors) private var accent

    var body: some View {
        Capsule()
            .fill(Palette.fill2)
            .frame(height: height)
            .overlay(alignment: .leading) {
                GeometryReader { geometry in
                    Capsule()
                        .fill(color ?? accent.accent)
                        .frame(width: geometry.size.width * min(max(value, 0), 1))
                }
            }
            .clipShape(Capsule())
    }
}

/// A progress ring, as the usage button shows it.
struct ProgressRing: View {
    let value: Double
    @Environment(\.accentColors) private var accent

    var body: some View {
        ZStack {
            Circle().stroke(Palette.fill2, lineWidth: 3.5)
            Circle()
                .trim(from: 0, to: min(max(value, 0), 1))
                .stroke(accent.accent, lineWidth: 3.5)
                .rotationEffect(.degrees(-90))
        }
        .frame(width: 15, height: 15)
        .padding(1.5)
        .accessibilityHidden(true)
    }
}

/// Buttons of the mockup: `.b` in ghost, plain, primary and destructive variants, in the
/// theme's control shape (pills, or Smoke's rounded rectangles).
struct HarnessButtonStyle: ButtonStyle {
    enum Kind {
        case ghost, plain, primary, approve, danger, destructive
    }

    var kind = Kind.plain
    var height: Double = 28
    var iconOnly = false
    var fontSize: Double = TypeSize.callout
    @Environment(\.accentColors) private var accent
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.glass) private var glass

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .font(.ui(fontSize, .semibold))
                .labelStyle(TightLabelStyle())
                .foregroundStyle(foreground)
                .padding(.horizontal, iconOnly ? 0 : (height < 28 ? 10 : 12))
                .frame(width: iconOnly ? height : nil, height: height)
                .background(background(hovering: hovering), in: glass.control)
                .contentShape(glass.control)
                .scaleEffect(configuration.isPressed ? 0.97 : 1)
                .opacity(isEnabled ? 1 : 0.35)
                .pointerStyle(isEnabled ? .link : nil)
        }
    }

    private var foreground: Color {
        switch kind {
        case .ghost: Palette.t2
        case .plain: Palette.t1
        case .primary: accent.onAccent
        case .approve, .destructive: .white
        case .danger: StatusTone.failed.textColor
        }
    }

    private func background(hovering: Bool) -> Color {
        switch kind {
        case .ghost: hovering ? Palette.fill : .clear
        case .plain: hovering ? Palette.fill2.opacity(1.4) : Palette.fill2
        case .primary: hovering ? accent.accent.opacity(0.9) : accent.accent
        case .approve: Palette.approve
        case .danger: StatusTone.failed.soft
        case .destructive: StatusTone.failed.color
        }
    }
}

extension ButtonStyle where Self == HarnessButtonStyle {
    static func harness(
        _ kind: HarnessButtonStyle.Kind = .plain, height: Double = 28, iconOnly: Bool = false
    ) -> HarnessButtonStyle {
        HarnessButtonStyle(
            kind: kind, height: height, iconOnly: iconOnly,
            fontSize: height < 28 ? TypeSize.label : TypeSize.callout)
    }
}

/// Icon and title with the mockup's 6 point gap.
struct TightLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) {
            configuration.icon.font(.system(size: 12, weight: .medium))
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

/// The small uppercase-free section header of the sidebar and cards.
struct SectionLabel: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.caption, .bold))
            .foregroundStyle(Palette.t3)
    }
}
