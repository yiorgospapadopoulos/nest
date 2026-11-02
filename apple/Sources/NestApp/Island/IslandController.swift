import AppKit
import ApplicationServices
import NestKit
import Observation

/// The island's window: borderless over the menu bar, on every space and over full-screen
/// apps, never key or main, so it neither takes the focus nor counts as Nest on screen.
final class IslandPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    /// It sits over the menu bar, where a window is otherwise pushed down.
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect {
        frameRect
    }
}

/// The island around the notch (B114): places its panel on the screen with the notch (or
/// the pill on the main screen), follows the store's state, the free menu bar space and
/// full-screen apps, and turns clicks into Nest's chats.
@MainActor @Observable
final class IslandController {
    /// Accessibility is granted: the wings may grow into the free menu bar.
    private(set) var trusted = AXIsProcessTrusted()

    /// Where the panel goes on screen and the island in it.
    private struct Placement {
        var screen: NSScreen
        var frame: CGRect
        var geometry: IslandGeometry
        /// The notch's edges on screen.
        var notchMinX: Double
        var notchMaxX: Double
    }

    @ObservationIgnored private let shell: Shell
    @ObservationIgnored private var panel: IslandPanel?
    @ObservationIgnored private var view: IslandView?
    @ObservationIgnored private var placement: Placement?
    @ObservationIgnored private let scanner = MenuBarScanner()
    @ObservationIgnored private var menuBar = MenuBarScanner.Items(menus: [], extras: [])
    @ObservationIgnored private var observers: [(NotificationCenter, any NSObjectProtocol)] = []
    @ObservationIgnored private var monitors: [Any] = []
    @ObservationIgnored private var timer: Timer?
    @ObservationIgnored private var pending = false
    /// Looks again while a finished pixie of the focused chat is still landing.
    @ObservationIgnored private var landing: Timer?
    @ObservationIgnored private var workingChats: [String] = []
    #if DEBUG
        @ObservationIgnored private var demo: IslandDemo?
    #endif

    init(shell: Shell) {
        self.shell = shell
    }

    private var island: IslandStore { shell.model.island }

    func start() {
        guard panel == nil else { return }
        let panel = IslandPanel(
            contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered,
            defer: true)
        panel.level = .statusBar
        panel.collectionBehavior = [
            .canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle,
        ]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.hidesOnDeactivate = false
        panel.isExcludedFromWindowsMenu = true
        panel.ignoresMouseEvents = true
        panel.isReleasedWhenClosed = false
        panel.animationBehavior = .none
        let view = IslandView(
            geometry: IslandGeometry(pill: true, notchMinX: 0, notchMaxX: 0, top: 0, height: 0))
        view.onClick = { [weak self] in self?.perform($0) }
        view.onHot = { [weak panel] in panel?.ignoresMouseEvents = !$0 }
        panel.contentView = view
        self.panel = panel
        self.view = view
        #if DEBUG
            if IslandDemo.isRequested {
                let demo = IslandDemo()
                demo.onChange = { [weak self] in self?.scheduleRefresh() }
                demo.onPin = { [weak view] in view?.pinList() }
                self.demo = demo
                demo.start()
            }
        #endif
        observe()
        place()
        scan(full: true)
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
    }

    /// Takes the panel down, as when the app switches daemons.
    func stop() {
        for (center, token) in observers {
            center.removeObserver(token)
        }
        observers = []
        for monitor in monitors {
            NSEvent.removeMonitor(monitor)
        }
        monitors = []
        timer?.invalidate()
        timer = nil
        landing?.invalidate()
        landing = nil
        #if DEBUG
            demo?.stop()
            demo = nil
        #endif
        view?.pause()
        panel?.orderOut(nil)
        panel?.contentView = nil
        panel = nil
        view = nil
    }

    /// Settings' Allow: asks for Accessibility and opens its page in System Settings.
    func allowAccessibility() {
        trusted = AXIsProcessTrustedWithOptions(
            ["AXTrustedCheckOptionPrompt": true] as CFDictionary)
        if !trusted,
            let url = URL(
                string:
                    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        {
            NSWorkspace.shared.open(url)
        }
    }

    // MARK: Watching

    private func observe() {
        let app = NotificationCenter.default
        add(app, NSApplication.didChangeScreenParametersNotification) { $0.place() }
        // Which chat is focused also depends on Nest's window being in front.
        add(app, NSApplication.didBecomeActiveNotification) { $0.scheduleRefresh() }
        add(app, NSWindow.didBecomeMainNotification) { $0.scheduleRefresh() }
        add(app, NSWindow.didChangeOcclusionStateNotification) { $0.scheduleRefresh() }
        let workspace = NSWorkspace.shared.notificationCenter
        add(workspace, NSWorkspace.didActivateApplicationNotification) { $0.scan(full: false) }
        add(workspace, NSWorkspace.didLaunchApplicationNotification) { $0.scan(full: false) }
        add(workspace, NSWorkspace.didTerminateApplicationNotification) { $0.scan(full: false) }
        add(workspace, NSWorkspace.accessibilityDisplayOptionsDidChangeNotification) {
            $0.scheduleRefresh()
        }
        // The panel ignores the pointer until it comes over the strip, so the pointer is
        // followed here: elsewhere on screen and over Nest's own windows.
        if let global = NSEvent.addGlobalMonitorForEvents(
            matching: [.mouseMoved, .leftMouseDragged],
            handler: { [weak self] _ in
                MainActor.assumeIsolated { self?.view?.pointer(at: NSEvent.mouseLocation) }
            })
        {
            monitors.append(global)
        }
        if let local = NSEvent.addLocalMonitorForEvents(
            matching: [.mouseMoved],
            handler: { [weak self] event in
                MainActor.assumeIsolated { self?.view?.pointer(at: NSEvent.mouseLocation) }
                return event
            })
        {
            monitors.append(local)
        }
    }

    private func add(
        _ center: NotificationCenter, _ name: Notification.Name,
        _ change: @escaping @MainActor (IslandController) -> Void
    ) {
        let token = center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                change(self)
            }
        }
        observers.append((center, token))
    }

    /// Every few seconds: Accessibility may have been granted, Nightshade may fall asleep
    /// and status items come and go.
    private func tick() {
        let granted = AXIsProcessTrusted()
        if granted != trusted {
            trusted = granted
        }
        scan(full: true)
        scheduleRefresh()
    }

    // MARK: Screen

    /// Always the main display set in System Settings, the one with the menu bar, and the
    /// same in full-screen apps (user 2026-11-02): around its notch when it has one, else
    /// the pill in its menu bar.
    private func place() {
        guard let panel, let view else { return }
        if let screen = NSScreen.screens.first,
            let leftArea = screen.auxiliaryTopLeftArea,
            let rightArea = screen.auxiliaryTopRightArea
        {
            let frame = screen.frame
            let notchMinX = frame.minX + leftArea.width
            let notchMaxX = frame.maxX - rightArea.width
            let bar = screen.safeAreaInsets.top > 0 ? screen.safeAreaInsets.top : leftArea.height
            let width = notchMaxX - notchMinX + 340
            let height = bar + 280
            let panelFrame = CGRect(
                x: ((notchMinX + notchMaxX) / 2 - width / 2).rounded(), y: frame.maxY - height,
                width: width, height: height)
            placement = Placement(
                screen: screen, frame: panelFrame,
                geometry: IslandGeometry(
                    pill: false, notchMinX: notchMinX - panelFrame.minX,
                    notchMaxX: notchMaxX - panelFrame.minX, top: 0, height: bar),
                notchMinX: notchMinX, notchMaxX: notchMaxX)
        } else if let screen = NSScreen.screens.first {
            let frame = screen.frame
            let menuBar = frame.maxY - screen.visibleFrame.maxY
            // As tall as the menu bar, but never shorter than a pixie and its margin.
            let bar = max(menuBar > 0 ? menuBar : NSStatusBar.system.thickness, 30)
            let width = 560.0
            let height = bar + 280
            let panelFrame = CGRect(
                x: (frame.midX - width / 2).rounded(), y: frame.maxY - height, width: width,
                height: height)
            let gap = IslandLayout.pillGap
            placement = Placement(
                screen: screen, frame: panelFrame,
                geometry: IslandGeometry(
                    pill: true, notchMinX: width / 2 - gap, notchMaxX: width / 2 + gap, top: 0,
                    height: bar),
                notchMinX: frame.midX - gap, notchMaxX: frame.midX + gap)
        } else {
            placement = nil
        }
        guard let placement else { return }
        panel.setFrame(placement.frame, display: false)
        view.frame = CGRect(origin: .zero, size: placement.frame.size)
        view.scene.geometry = placement.geometry
        scheduleRefresh()
    }

    /// Reads the menu bar's items with Accessibility, away from the main thread.
    private func scan(full: Bool) {
        guard trusted, let placement, !placement.geometry.pill else { return }
        let apps = NSWorkspace.shared.runningApplications
            .filter { $0.activationPolicy != .prohibited }
            .map(\.processIdentifier)
        scanner.scan(
            front: NSWorkspace.shared.frontmostApplication?.processIdentifier, apps: apps,
            full: full
        ) { [weak self] items in
            self?.menuBar = items
            self?.scheduleRefresh()
        }
    }

    /// Each side's free width: the smallest form without Accessibility.
    private func freeWidths(_ placement: Placement) -> (left: Double, right: Double) {
        guard trusted, !placement.geometry.pill else {
            return IslandLayout.freeWidth(
                notchMinX: placement.notchMinX, notchMaxX: placement.notchMaxX, appMenuMaxX: nil,
                statusItemMinX: nil)
        }
        let edges = MenuBarSpace.edges(
            of: menuBar, screen: placement.screen, barHeight: placement.geometry.height,
            notchMinX: placement.notchMinX, notchMaxX: placement.notchMaxX)
        return IslandLayout.freeWidth(
            notchMinX: placement.notchMinX, notchMaxX: placement.notchMaxX,
            appMenuMaxX: edges.appMenuMaxX, statusItemMinX: edges.statusItemMinX)
    }

    // MARK: State

    private func scheduleRefresh() {
        guard !pending else { return }
        pending = true
        Task { @MainActor [weak self] in
            self?.pending = false
            self?.refresh()
        }
    }

    /// Reads the island's state again, now and whenever what it reads changes.
    private func refresh() {
        guard let panel, let view, let placement else { return }
        let pill = placement.geometry.pill
        let state: IslandState
        #if DEBUG
            if let demo {
                state = demo.state(pill: pill)
                show(state, placement: placement, panel: panel, view: view)
                return
            }
        #endif
        var focused: String?
        state = withObservationTracking {
            focused = focusedChat()
            return island.state(pill: pill)
        } onChange: { [weak self] in
            Task { @MainActor in self?.scheduleRefresh() }
        }
        show(state, placement: placement, panel: panel, view: view)
        if state.workingChats != workingChats {
            workingChats = state.workingChats
            Task { await island.loadActivity(state) }
        }
        see(focused, in: state, view: view)
    }

    private func show(
        _ state: IslandState, placement: Placement, panel: IslandPanel, view: IslandView
    ) {
        let reduce = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        if view.scene.reduceMotion != reduce {
            view.scene.reduceMotion = reduce
            view.redraw()
        }
        guard !state.isHidden else {
            view.pause()
            panel.orderOut(nil)
            return
        }
        let free = freeWidths(placement)
        view.show(
            state,
            fit: IslandLayout.fit(
                state, left: free.left, right: free.right, pill: placement.geometry.pill))
        if !panel.isVisible {
            panel.orderFrontRegardless()
        }
    }

    /// The chat focused in Nest's frontmost window, if any.
    private func focusedChat() -> String? {
        let windowFocused =
            NSApp.isActive && NSApp.mainWindow?.isVisible == true
            && NSApp.mainWindow?.occlusionState.contains(.visible) == true
        return NotificationPolicy.focusedChat(
            app: shell.app, pixies: shell.pixies.pixies, pixiesOpen: shell.pixiesOpen,
            windowFocused: windowFocused)
    }

    /// Only the focused chat is seen (user 2026-11-02): its pixies that need the user turn
    /// calm, and its finished ones pop once they have landed on the right. A chat that is
    /// on screen but not focused keeps its pixies until it is focused.
    private func see(_ chat: String?, in state: IslandState, view: IslandView) {
        landing?.invalidate()
        landing = nil
        guard let chat else { return }
        let finished: Set<IslandStatus> = [.done, .failed, .interrupted]
        let unseen = state.list.filter {
            $0.place.sessionID == chat && $0.status != .working && $0.status != .seen
        }
        guard !unseen.isEmpty else { return }
        let ending = unseen.filter { finished.contains($0.status) }
        guard ending.allSatisfy({ view.scene.hasLanded($0.id) }) else {
            landing = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: false) {
                [weak self] _ in
                MainActor.assumeIsolated { self?.scheduleRefresh() }
            }
            return
        }
        for entry in ending {
            view.scene.pop(entry.id)
        }
        island.markSeen(chat: chat)
    }

    // MARK: Clicks

    private func perform(_ target: IslandTarget) {
        // A click opens a done, failed or interrupted pixie's chat and it leaves with a pop;
        // hiding for any other reason only fades.
        if case .entry(let entry) = target,
            [.done, .failed, .interrupted].contains(entry.status)
        {
            view?.scene.pop(entry.id)
        }
        #if DEBUG
            if let demo {
                if target == .more {
                    view?.pinList()
                } else {
                    demo.click(target)
                }
                return
            }
        #endif
        switch island.click(target) {
        case .openNest:
            bringNestForward()
        case .open(let place):
            bringNestForward()
            open(place)
        case .openApproval(let place, let id):
            bringNestForward()
            open(place)
            if let approval = shell.approval(id) {
                shell.foldedRows[approval.foldKey] = true
            }
            if !shell.pixiesOpen {
                shell.update { $0.rightCollapsed = false }
            }
        case .showList:
            view?.pinList()
        }
    }

    /// The chat the work happens in.
    private func open(_ place: IslandPlace) {
        switch place {
        case .chat(let session, let repo):
            if let repo = repo ?? shell.sessions.session(session)?.repo {
                shell.reveal(chat: session, in: repo)
            }
        case .pixieChat(let pixie, _):
            shell.revealPixie(pixie)
        case .habitRun(let session):
            shell.openHabitRun(session)
        }
    }

    /// Brings Nest's window to the front, as a notification's click does.
    private func bringNestForward() {
        NSApp.activate()
        if let window = NSApp.windows.first(where: { $0.isVisible && $0.canBecomeMain }) {
            window.makeKeyAndOrderFront(nil)
        } else {
            shell.showMainWindow()
        }
    }
}
