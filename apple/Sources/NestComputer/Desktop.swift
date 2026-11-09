import AppKit
import ApplicationServices
import NestComputerCore

/// The apps, windows and elements the helper knows, with their ids.
///
/// A window on another desktop is missing from its app's `AXWindows`, so every window the
/// helper has seen is kept, and an observer on each app it touched adds the windows the app
/// creates later, wherever they open (B150 spike).
@MainActor
final class Desktop {
    struct Window {
        let id: String
        let element: AXUIElement
        let pid: pid_t
        let onThisDesktop: Bool
    }

    private var windows = IDRegistry<AXUIElement>(prefix: "w")
    private var elements = IDRegistry<AXUIElement>(prefix: "e")
    private var observers: [pid_t: AXObserver] = [:]
    private var enhanced: Set<pid_t> = []
    /// Window ids in the order their apps announced them, for `menu`'s new windows.
    private(set) var created: [String] = []

    init() {
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didTerminateApplicationNotification, object: nil, queue: .main
        ) { [weak self] note in
            let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            guard let pid = app?.processIdentifier else { return }
            MainActor.assumeIsolated { self?.forget(pid) }
        }
    }

    // MARK: Apps

    func apps() -> [JSONValue] {
        let own = ProcessInfo.processInfo.processIdentifier
        return NSWorkspace.shared.runningApplications
            .filter { $0.activationPolicy == .regular && $0.processIdentifier != own }
            .map { app in
                let pid = app.processIdentifier
                return [
                    "pid": .int(Int(pid)), "bundle_id": .optional(app.bundleIdentifier),
                    "name": .optional(app.localizedName), "active": .bool(app.isActive),
                    "hidden": .bool(app.isHidden),
                    "windows": .array(windows(of: pid).map(json)),
                ]
            }
    }

    /// The app's windows: those on this desktop, then those seen before.
    func windows(of pid: pid_t) -> [Window] {
        observe(pid)
        let app = AXUIElementCreateApplication(pid)
        let owner = String(pid)
        var here: Set<String> = []
        for element in AX.elements(app, kAXWindowsAttribute) {
            here.insert(windows.id(for: element, owner: owner))
        }
        var result: [Window] = []
        for id in windows.ids(owner: owner) {
            guard case .found(let element, _) = windows.lookup(id), AX.isAlive(element) else {
                retireWindow(id)
                continue
            }
            result.append(
                Window(id: id, element: element, pid: pid, onThisDesktop: here.contains(id)))
        }
        return result.sorted { $0.onThisDesktop && !$1.onThisDesktop }
    }

    func json(_ window: Window) -> JSONValue {
        [
            "id": .string(window.id),
            "title": .optional(AX.string(window.element, kAXTitleAttribute)),
            "minimized": .bool(AX.bool(window.element, kAXMinimizedAttribute) ?? false),
            "on_this_desktop": .bool(window.onThisDesktop),
            "frame": AX.frame(window.element)?.json ?? .null,
        ]
    }

    // MARK: Lookups

    func window(_ id: String) throws(HelperError) -> Window {
        switch windows.lookup(id) {
        case .found(let element, let owner):
            guard AX.isAlive(element), let pid = pid_t(owner) else {
                retireWindow(id)
                throw HelperError(.stale, "window \(id) is closed")
            }
            let here = AX.elements(AXUIElementCreateApplication(pid), kAXWindowsAttribute)
            return Window(id: id, element: element, pid: pid, onThisDesktop: here.contains(element))
        case .stale: throw HelperError(.stale, "window \(id) is closed")
        case .unknown: throw HelperError(.notFound, "no window \(id); list the apps first")
        }
    }

    func element(_ id: String) throws(HelperError) -> (element: AXUIElement, window: Window) {
        switch elements.lookup(id) {
        case .found(let element, let windowID):
            let window = try window(windowID)
            guard AX.isAlive(element) else {
                elements.retire(id)
                throw HelperError(.stale, "element \(id) is gone; read the window again")
            }
            return (element, window)
        case .stale: throw HelperError(.stale, "element \(id) is gone; read the window again")
        case .unknown: throw HelperError(.notFound, "no element \(id); read the window first")
        }
    }

    func elementID(_ element: AXUIElement, window: String) -> String {
        elements.id(for: element, owner: window)
    }

    // MARK: Touching apps

    /// Readies an app for reading and acting: an observer for its new windows and, for
    /// Chromium and Electron apps, their accessibility tree switched on (it takes a moment
    /// to build the first time).
    func prepare(_ pid: pid_t) async {
        observe(pid)
        guard !enhanced.contains(pid) else { return }
        enhanced.insert(pid)
        guard isChromium(pid) else { return }
        let app = AXUIElementCreateApplication(pid)
        _ = AX.set(app, "AXEnhancedUserInterface", kCFBooleanTrue)
        _ = AX.set(app, "AXManualAccessibility", kCFBooleanTrue)
        try? await Task.sleep(for: .seconds(1))
    }

    private func isChromium(_ pid: pid_t) -> Bool {
        guard let bundle = NSRunningApplication(processIdentifier: pid)?.bundleURL else {
            return false
        }
        let folder = bundle.appending(path: "Contents/Frameworks", directoryHint: .isDirectory)
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? []
        return Roles.isChromium(frameworks: names)
    }

    func observe(_ pid: pid_t) {
        guard observers[pid] == nil else { return }
        var observer: AXObserver?
        guard AXObserverCreate(pid, windowCreated, &observer) == .success, let observer else {
            return
        }
        let refcon = Unmanaged.passUnretained(self).toOpaque()
        let added = AXObserverAddNotification(
            observer, AXUIElementCreateApplication(pid),
            kAXWindowCreatedNotification as CFString, refcon)
        guard added == .success else { return }
        CFRunLoopAddSource(
            CFRunLoopGetMain(), AXObserverGetRunLoopSource(observer), .defaultMode)
        observers[pid] = observer
    }

    fileprivate func noteCreated(_ element: AXUIElement) {
        guard AX.role(element) == kAXWindowRole, let pid = AX.pid(element) else { return }
        created.append(windows.id(for: element, owner: String(pid)))
    }

    private func forget(_ pid: pid_t) {
        if let observer = observers.removeValue(forKey: pid) {
            CFRunLoopRemoveSource(
                CFRunLoopGetMain(), AXObserverGetRunLoopSource(observer), .defaultMode)
        }
        enhanced.remove(pid)
        for id in windows.ids(owner: String(pid)) { retireWindow(id) }
    }

    private func retireWindow(_ id: String) {
        windows.retire(id)
        elements.retire(owner: id)
    }
}

/// Runs on the main run loop, where the observers' sources are.
private func windowCreated(
    _ observer: AXObserver, _ element: AXUIElement, _ notification: CFString,
    _ refcon: UnsafeMutableRawPointer?
) {
    guard let refcon else { return }
    let desktop = Unmanaged<Desktop>.fromOpaque(refcon).takeUnretainedValue()
    // The element is used only here, on the main thread it arrived on.
    nonisolated(unsafe) let window = element
    MainActor.assumeIsolated { desktop.noteCreated(window) }
}
