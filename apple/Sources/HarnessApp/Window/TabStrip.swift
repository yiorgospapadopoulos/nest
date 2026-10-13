import AppKit
import HarnessKit
import SwiftUI

/// The Pixies tab and the project tabs across the top of the window, with the usage meter
/// and search.
struct TabStrip: View {
    /// Room for the window's traffic lights.
    static let leadingInset = 86.0

    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass
    @State private var addingProject = false
    /// Add folder was picked: the panel opens once the popover has gone.
    @State private var choosingFolder = false

    var body: some View {
        HStack(alignment: .bottom, spacing: 4) {
            PixiesTab()
            ForEach(shell.app.openProjects, id: \.self) { name in
                ProjectTab(name: name)
            }
            addButton
            Spacer(minLength: 12)
            HStack(spacing: 8) {
                UsageButton()
                SearchButton()
            }
            .frame(height: glass.spacing.stripHeight)
        }
        .padding(.leading, Self.leadingInset)
        .padding(.trailing, 12)
        .frame(height: glass.spacing.stripHeight)
        .background(glass.strip)
        .background(WindowDragArea())
    }

    private var addButton: some View {
        Button {
            addingProject.toggle()
        } label: {
            Image(systemName: Icon.plus).font(.system(size: 13, weight: .medium))
        }
        .buttonStyle(StripIconStyle())
        .padding(.bottom, max(0, (glass.spacing.stripHeight - 30) / 2 - 3))
        .help("Open another project")
        .accessibilityLabel("Open another project")
        .popover(isPresented: $addingProject, arrowEdge: .bottom) {
            AddProjectPopover {
                addingProject = false
            } chooseFolder: {
                choosingFolder = true
                addingProject = false
            }
            .environment(shell)
            .onDisappear {
                guard choosingFolder else { return }
                choosingFolder = false
                // The next turn of the run loop, so the sheet slides down from the window
                // instead of racing the popover's close.
                DispatchQueue.main.async {
                    FolderPicker.present { shell.addProject(at: $0) }
                }
            }
        }
    }
}

/// One project tab; the current one rises into the window body.
private struct ProjectTab: View {
    let name: String
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion
    @Environment(\.glass) private var glass
    @State private var hovering = false

    var body: some View {
        let isCurrent = shell.project == name && !shell.pixiesOpen
        let strip = glass.spacing.stripHeight
        let attention = shell.sessions.attention(of: name)
        let running = shell.sessions.sessions(in: name).contains {
            $0.state == .running || $0.state == .starting
        }
        let glowing = !isCurrent && attention > 0
        let canClose = shell.app.openProjects.count > 1

        HStack(spacing: 8) {
            ProjectMarkView(name: name)
            Text(name)
                .font(.ui(TypeSize.callout, .semibold))
                .foregroundStyle(isCurrent ? Palette.t1 : Palette.t2)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            if attention > 0 {
                CountBadge(count: attention, urgent: true, size: 18)
            } else if running {
                StatusDot(tone: .running, size: 7)
            }
        }
        .padding(.leading, 10)
        .padding(.trailing, 30)
        .frame(minWidth: 118, maxWidth: 196)
        .frame(height: isCurrent ? strip - 9 : strip - 16)
        .background {
            if isCurrent {
                TabShape(radius: glass.radius.tab).fill(glass.shell)
                    .padding(.horizontal, -glass.radius.tab)
            } else if glowing {
                AttentionGlow(reduceMotion: reduceMotion, radius: glass.radius.item)
            } else if hovering {
                glass.rounded(glass.radius.item).fill(Palette.fill)
            }
        }
        .overlay(alignment: .trailing) {
            if canClose && (hovering || isCurrent) {
                Button {
                    shell.app.closeProject(name)
                } label: {
                    Image(systemName: Icon.close).font(.system(size: 9, weight: .semibold))
                }
                .buttonStyle(SmallSquareStyle())
                .padding(.trailing, 6)
                .help("Close \(name)")
                .accessibilityLabel("Close \(name)")
            }
        }
        .contentShape(Rectangle())
        .pointerStyle(.link)
        .onTapGesture { shell.selectProject(name) }
        .onHover { hovering = $0 }
        .padding(.bottom, isCurrent ? 0 : 5)
        .zIndex(isCurrent ? 1 : 0)
        .help(attention > 0 ? "\(name), \(attention) need you" : name)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(isCurrent ? [.isButton, .isSelected] : .isButton)
        .accessibilityLabel(attention > 0 ? "\(name), \(attention) need you" : name)
    }
}

/// The leftmost tab (Cmd-0): the user's pixies, whichever project is open. It glows like a
/// project tab while a pixie's chat needs the user.
private struct PixiesTab: View {
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion
    @Environment(\.glass) private var glass
    @State private var hovering = false

    var body: some View {
        let isCurrent = shell.pixiesOpen
        let strip = glass.spacing.stripHeight
        let attention = shell.approvals.pending.count { Pixie.id(ofRepo: $0.repo) != nil }
        let running = shell.pixies.visible.contains { pixie in
            let state = pixie.chatSessionID.flatMap(shell.sessions.session)?.state
            return state == .running || state == .starting
        }
        let mascot = shell.shownPixie ?? shell.pixies.visible.first
        HStack(spacing: 8) {
            SpriteView(
                mascot: mascot?.mascot ?? .invader, color: mascot?.color ?? PixieColor.standard,
                size: 20)
            Text("Pixies")
                .font(.ui(TypeSize.callout, .semibold))
                .foregroundStyle(isCurrent ? Palette.t1 : Palette.t2)
                .lineLimit(1)
            if attention > 0 {
                CountBadge(count: attention, urgent: true, size: 18)
            } else if running {
                StatusDot(tone: .running, size: 7)
            }
        }
        .padding(.horizontal, 12)
        .frame(height: isCurrent ? strip - 9 : strip - 16)
        .background {
            if isCurrent {
                TabShape(radius: glass.radius.tab).fill(glass.shell)
                    .padding(.horizontal, -glass.radius.tab)
            } else if attention > 0 {
                AttentionGlow(reduceMotion: reduceMotion, radius: glass.radius.item)
            } else if hovering {
                glass.rounded(glass.radius.item).fill(Palette.fill)
            }
        }
        .contentShape(Rectangle())
        .pointerStyle(.link)
        .onTapGesture { shell.openPixies() }
        .onHover { hovering = $0 }
        .padding(.bottom, isCurrent ? 0 : 5)
        .zIndex(isCurrent ? 1 : 0)
        .help(attention > 0 ? "Pixies, \(attention) need you (⌘0)" : "Pixies (⌘0)")
        .accessibilityElement(children: .ignore)
        .accessibilityAddTraits(isCurrent ? [.isButton, .isSelected] : .isButton)
        .accessibilityLabel(attention > 0 ? "Pixies, \(attention) need you" : "Pixies")
        .accessibilityAction { shell.openPixies() }
    }
}

/// The current tab: rounded top corners and outward curves where it meets the body.
struct TabShape: Shape {
    var radius = 12.0

    func path(in rect: CGRect) -> Path {
        var path = Path()
        let flare = radius
        let left = rect.minX + flare
        let right = rect.maxX - flare
        path.move(to: CGPoint(x: rect.minX, y: rect.maxY))
        path.addQuadCurve(
            to: CGPoint(x: left, y: rect.maxY - flare), control: CGPoint(x: left, y: rect.maxY))
        path.addLine(to: CGPoint(x: left, y: rect.minY + radius))
        path.addQuadCurve(
            to: CGPoint(x: left + radius, y: rect.minY), control: CGPoint(x: left, y: rect.minY))
        path.addLine(to: CGPoint(x: right - radius, y: rect.minY))
        path.addQuadCurve(
            to: CGPoint(x: right, y: rect.minY + radius), control: CGPoint(x: right, y: rect.minY))
        path.addLine(to: CGPoint(x: right, y: rect.maxY - flare))
        path.addQuadCurve(
            to: CGPoint(x: rect.maxX, y: rect.maxY), control: CGPoint(x: right, y: rect.maxY))
        path.closeSubpath()
        return path
    }
}

/// The amber glow of a background tab that needs the user; steady with Reduce Motion.
private struct AttentionGlow: View {
    let reduceMotion: Bool
    let radius: Double

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        if reduceMotion {
            glow(shape, strong: true)
        } else {
            PhaseAnimator([false, true]) { strong in
                glow(shape, strong: strong)
            } animation: { _ in
                .easeInOut(duration: DesignTokens.Motion.Duration.attention / 2)
            }
        }
    }

    private func glow(_ shape: RoundedRectangle, strong: Bool) -> some View {
        shape
            .fill(StatusTone.waiting.soft)
            .overlay(
                shape.stroke(
                    strong ? StatusTone.waiting.color : Palette.attentionGlow, lineWidth: 1)
            )
            .shadow(color: Palette.attentionGlow, radius: strong ? 11 : 5)
    }
}

/// The usage meter: the 5 hour and weekly limits, live, dimmed once more than 10 minutes old.
private struct UsageButton: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        let fiveHour = usage.limits?.fiveHour
        let week = usage.limits?.sevenDay
        TimelineView(.everyMinute) { context in
            let staleFiveHour = UsageText.isStale(fiveHour, now: context.date)
            let staleWeek = UsageText.isStale(week, now: context.date)
            Button {
                shell.toggle(.usage)
            } label: {
                HStack(spacing: 8) {
                    ProgressRing(value: fiveHour?.utilization ?? 0)
                        .opacity(staleFiveHour ? 0.5 : 1)
                    Text("5h \(value(fiveHour, stale: staleFiveHour))")
                    Rectangle().fill(Palette.hair2).frame(width: 1, height: 14)
                    Text("Week \(value(week, stale: staleWeek))")
                }
                .font(.ui(TypeSize.small))
                .foregroundStyle(Palette.t2)
                .padding(.leading, 8)
                .padding(.trailing, 11)
            }
            .buttonStyle(StripFieldStyle())
            .help(help(fiveHour ?? week, stale: staleFiveHour || staleWeek))
            .accessibilityLabel(
                "Usage: 5 hour window \(UsageText.percent(fiveHour)), weekly \(UsageText.percent(week))"
            )
        }
    }

    private func value(_ window: LimitWindow?, stale: Bool) -> Text {
        Text(UsageText.percent(window)).foregroundStyle(stale ? Palette.t3 : Palette.t1).bold()
    }

    /// "Usage, as of 14:05", noting numbers more than 10 minutes old.
    private func help(_ window: LimitWindow?, stale: Bool) -> String {
        guard let asOf = shell.model.usage.asOfText(window) else { return "Usage" }
        return stale ? "Usage, \(asOf) (more than 10 minutes old)" : "Usage, \(asOf)"
    }
}

private struct SearchButton: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.show(.palette)
        } label: {
            HStack(spacing: 8) {
                Image(systemName: Icon.search).font(.system(size: 12, weight: .medium))
                Text("Search")
                Spacer(minLength: 0)
                Text("⌘K")
                    .font(.ui(10.5, .semibold))
                    .foregroundStyle(Palette.t2)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 3)
                    .background(Palette.fill2, in: RoundedRectangle(cornerRadius: 5))
            }
            .font(.ui(TypeSize.callout))
            .foregroundStyle(Palette.t3)
            .padding(.leading, 10)
            .padding(.trailing, 6)
            .frame(width: 170)
        }
        .buttonStyle(StripFieldStyle())
        .accessibilityLabel("Search chats and commands")
    }
}

/// Open repos to pick from, or a folder to add.
private struct AddProjectPopover: View {
    let dismiss: () -> Void
    let chooseFolder: () -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            SectionLabel(text: "Open a project")
                .padding(.horizontal, 9)
                .padding(.bottom, 6)
            ForEach(shell.app.closedRepos) { repo in
                MenuRow(icon: nil, title: repo.name, detail: repo.path) {
                    shell.app.openProject(repo.name)
                    dismiss()
                }
            }
            if !shell.app.closedRepos.isEmpty {
                Divider().padding(.vertical, 4)
            }
            MenuRow(icon: Icon.folder, title: "Add folder…", detail: nil, action: chooseFolder)
        }
        .padding(10)
        .frame(width: 280)
    }
}

/// The folder panel, as a sheet on the window; a window of its own only when there is none.
@MainActor
enum FolderPicker {
    static func present(then open: @escaping @MainActor (URL) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        panel.prompt = "Open"
        panel.message = "Choose a folder to open as a project"
        guard let window = NSApp.mainWindow ?? NSApp.keyWindow else {
            if panel.runModal() == .OK, let url = panel.url {
                open(url)
            }
            return
        }
        panel.beginSheetModal(for: window) { response in
            if response == .OK, let url = panel.url {
                open(url)
            }
        }
    }
}

/// A row of a popover list.
struct MenuRow: View {
    let icon: String?
    let title: String
    let detail: String?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                if let icon {
                    Image(systemName: icon).frame(width: 14)
                } else {
                    ProjectMarkView(name: title)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(.ui(TypeSize.callout))
                    if let detail {
                        Text(detail)
                            .font(.mono(10.5))
                            .foregroundStyle(Palette.t3)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 9)
            .padding(.vertical, 7)
            .contentShape(Rectangle())
        }
        .buttonStyle(RowHoverStyle())
    }
}

/// Fill-backed buttons of the strip (usage, search).
struct StripFieldStyle: ButtonStyle {
    @Environment(\.glass) private var glass

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .frame(height: 30)
                .background(
                    hovering || configuration.isPressed ? Palette.fill2 : Palette.fill,
                    in: glass.rounded(glass.radius.item)
                )
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

/// The strip's square icon buttons, such as add project.
struct StripIconStyle: ButtonStyle {
    @Environment(\.glass) private var glass

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(Palette.t2)
                .frame(width: 30, height: 30)
                .background(hovering ? Palette.fill : .clear, in: glass.rounded(glass.radius.item))
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

/// Tiny square buttons such as a tab's close button.
struct SmallSquareStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(hovering ? Palette.t1 : Palette.t3)
                .frame(width: 18, height: 18)
                .background(
                    hovering ? Palette.fill2 : .clear, in: RoundedRectangle(cornerRadius: 5)
                )
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

/// List rows that highlight on hover, in the theme's item corners unless given others.
struct RowHoverStyle: ButtonStyle {
    var radius: Double?
    @Environment(\.glass) private var glass

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(Palette.t1)
                .background(
                    hovering || configuration.isPressed ? Palette.fill : .clear,
                    in: glass.rounded(radius ?? glass.radius.item)
                )
                .pointerStyle(.link)
        }
    }
}

/// Lets the empty parts of the strip move the window, as a title bar does.
private struct WindowDragArea: View {
    var body: some View {
        Color.clear
            .contentShape(Rectangle())
            .gesture(WindowDragGesture())
            .allowsWindowActivationEvents(true)
    }
}
