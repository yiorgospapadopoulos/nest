import AppKit
import NestKit
import QuartzCore
import SwiftUI

/// The island panel's content: draws the scene, wakes only when something moves, opens
/// the list on hover and turns clicks into targets. The scene is drawn on a canvas that
/// covers only the strip while nothing grows or flies below it, so a frame uploads a
/// small backing store.
@MainActor
final class IslandView: NSView {
    let scene: IslandScene
    let list = IslandListModel()
    /// A click on a pixie, a +N, the strip or a row.
    var onClick: (IslandTarget) -> Void = { _ in }
    /// The pointer came over the strip or the open list, or left them: the panel takes
    /// clicks only while it is.
    var onHot: (Bool) -> Void = { _ in }
    /// Milliseconds; snapshots hold it still.
    var clock: () -> Double = { CACurrentMediaTime() * 1000 }

    private let under = IslandLayers(.under)
    private let canvas = IslandCanvas()
    private let over = IslandLayers(.over)
    private let listHost: IslandListHost
    private var link: CADisplayLink?
    private var wake: Timer?
    private var closing: Timer?
    private var hovering = false
    /// The link's frame interval in milliseconds, and when the last frame was drawn.
    private var interval = 0.0
    private var lastFrame = -Double.infinity
    private var hot = false
    /// Hidden: no frames at all.
    private var paused = true

    init(geometry: IslandGeometry) {
        scene = IslandScene(geometry: geometry)
        listHost = IslandListHost(rootView: IslandListView(model: list))
        super.init(frame: .zero)
        wantsLayer = true
        scene.usesLayers = true
        canvas.draws = { [weak self] context in self?.render(in: context) }
        addSubview(under)
        addSubview(canvas)
        addSubview(over)
        listHost.sizingOptions = []
        listHost.isHidden = true
        addSubview(listHost)
        list.click = { [weak self] in self?.onClick($0) }
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) is not supported")
    }

    override var isFlipped: Bool { true }
    override var isOpaque: Bool { false }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    /// Shows a new state: the scene animates toward it.
    func show(_ state: IslandState, fit: IslandFit) {
        guard paused || state != scene.state || fit != scene.fit else { return }
        scene.update(state, fit: fit)
        if list.entries != state.list {
            list.entries = state.list
        }
        paused = false
        redraw()
    }

    /// Everything at rest at one moment, drawn once: for snapshots.
    func hold(at time: Double, usesLayers: Bool = false) {
        clock = { time }
        // Offscreen captures see only what is drawn, so the strip and glows are drawn too,
        // unless the capture renders the layers.
        scene.usesLayers = usesLayers
        scene.settle(at: time)
        paused = true
        fitCanvas()
        canvas.needsDisplay = true
    }

    /// Stops drawing while the panel is hidden.
    func pause() {
        paused = true
        link?.isPaused = true
        wake?.invalidate()
        wake = nil
        closing?.invalidate()
        closing = nil
        hovering = false
        scene.wantsOpen = false
        setHot(false)
    }

    /// The +N: opens the list until the pointer leaves.
    func pinList() {
        hovering = true
        closing?.invalidate()
        closing = nil
        scene.wantsOpen = true
        redraw()
    }

    override func setFrameSize(_ newSize: NSSize) {
        super.setFrameSize(newSize)
        under.frame = bounds
        over.frame = bounds
        fitCanvas()
    }

    private func render(in context: CGContext) {
        let pace = scene.render(in: context, at: clock())
        lastFrame = clock()
        let effects = scene.usesLayers ? scene.effects : IslandEffects()
        under.show(effects, animated: !scene.reduceMotion)
        over.show(effects, animated: !scene.reduceMotion)
        place()
        // The list opened or closed, or a flight began or ended: the canvas changes size
        // with the next frame, never inside this draw, or this frame shows stretched.
        if canvasFrame != canvas.frame {
            DispatchQueue.main.async { [weak self] in self?.redraw() }
        }
        if !paused {
            schedule(pace)
        }
    }

    /// The strip, or the whole view while the list is open or something flies
    /// under the strip; true when it changed.
    @discardableResult
    private func fitCanvas() -> Bool {
        let frame = canvasFrame
        guard canvas.frame != frame else { return false }
        canvas.frame = frame
        return true
    }

    private var canvasFrame: CGRect {
        scene.wantsOpen ? bounds : (scene.drawnRect?.intersection(bounds) ?? bounds).integral
    }

    /// The list's frame and fade follow the scene's.
    private func place() {
        let frame = scene.listFrame
        if listHost.frame != frame {
            listHost.frame = frame
        }
        let alpha = scene.listAlpha
        listHost.isHidden = alpha <= 0
        if listHost.alphaValue != alpha {
            listHost.alphaValue = alpha
        }
    }

    // MARK: Pace

    private func schedule(_ pace: IslandPace) {
        wake?.invalidate()
        wake = nil
        switch pace {
        case .smooth:
            run(fps: 60)
        case .hop:
            run(fps: 20)
        case .at, .still:
            link?.isPaused = true
        }
        // A hop or a blink starts on time even between slow frames.
        if pace != .smooth, let next = scene.nextChange {
            let delay = max(0.005, (next - clock()) / 1000)
            wake = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
                MainActor.assumeIsolated { self?.redraw() }
            }
        }
    }

    /// A hop in place wants far fewer frames than a flight. The display link may tick
    /// faster than asked, so ticks closer than the rate allows are skipped.
    private func run(fps: Float) {
        let link = self.link ?? makeLink()
        let range = CAFrameRateRange(minimum: fps / 2, maximum: fps, preferred: fps)
        if link.preferredFrameRateRange != range {
            link.preferredFrameRateRange = range
        }
        interval = 1000 / Double(fps)
        link.isPaused = false
    }

    private func makeLink() -> CADisplayLink {
        let link = displayLink(target: self, selector: #selector(tick))
        link.add(to: .main, forMode: .common)
        self.link = link
        return link
    }

    @objc private func tick() {
        guard clock() - lastFrame >= interval - 4 else { return }
        redraw()
    }

    /// Draws the next frame now.
    func redraw() {
        fitCanvas()
        canvas.needsDisplay = true
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if window == nil {
            link?.invalidate()
            link = nil
            wake?.invalidate()
            wake = nil
        }
    }

    // MARK: Pointer

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas {
            removeTrackingArea(area)
        }
        addTrackingArea(
            NSTrackingArea(
                rect: .zero,
                options: [.mouseMoved, .mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                owner: self))
    }

    override func mouseMoved(with event: NSEvent) {
        pointer(at: NSEvent.mouseLocation)
    }

    override func mouseEntered(with event: NSEvent) {
        pointer(at: NSEvent.mouseLocation)
    }

    override func mouseExited(with event: NSEvent) {
        pointer(at: NSEvent.mouseLocation)
    }

    /// The pointer at a point on screen: over the strip or the open list the island takes
    /// clicks and opens the list; 250 ms after it leaves, the list closes.
    func pointer(at screenPoint: NSPoint) {
        guard !paused, let window else { return }
        let point = convert(window.convertPoint(fromScreen: screenPoint), from: nil)
        let inside = isHot(point)
        setHot(inside)
        if inside {
            closing?.invalidate()
            closing = nil
            if !hovering {
                hovering = true
                scene.wantsOpen = true
                redraw()
            }
        } else if hovering && closing == nil {
            closing = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: false) {
                [weak self] _ in
                MainActor.assumeIsolated {
                    guard let self else { return }
                    self.closing = nil
                    self.hovering = false
                    self.scene.wantsOpen = false
                    self.redraw()
                }
            }
        }
    }

    private func isHot(_ point: CGPoint) -> Bool {
        scene.stripRect.contains(point)
            || (scene.open > 0.5 && scene.listFrame.contains(point))
    }

    private func setHot(_ value: Bool) {
        guard hot != value else { return }
        hot = value
        onHot(value)
    }

    override func hitTest(_ point: NSPoint) -> NSView? {
        let local = convert(point, from: superview)
        return isHot(local) ? super.hitTest(point) : nil
    }

    override func mouseUp(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        guard scene.stripRect.contains(point) else { return }
        let hit = scene.hits.first { $0.rect.contains(point) }
        onClick(hit?.target ?? .strip)
    }

    override func mouseDown(with event: NSEvent) {}

    // MARK: Accessibility

    // The scene is drawn, not made of views: VoiceOver gets one group summing it up, with
    // a button for the strip and for each pixie and +N, which act as their clicks do.

    override func isAccessibilityElement() -> Bool { true }
    override func accessibilityRole() -> NSAccessibility.Role? { .group }
    override func accessibilityLabel() -> String? { scene.state.accessibilitySummary }

    override func accessibilityChildren() -> [Any]? {
        let strip = IslandHitElement(
            label: "Open Nest", frame: scene.stripRect, parent: self
        ) { [weak self] in self?.onClick(.strip) }
        let hits = scene.hits.map { hit in
            IslandHitElement(label: Self.label(of: hit.target), frame: hit.rect, parent: self) {
                [weak self] in self?.onClick(hit.target)
            }
        }
        return [strip] + hits + (listHost.isHidden ? [] : [listHost])
    }

    private static func label(of target: IslandTarget) -> String {
        switch target {
        case .strip: "Open Nest"
        case .more: "Show all pixies"
        case .entry(let entry): "\(entry.label), \(entry.status.word)"
        }
    }
}

/// A button on the drawn island for VoiceOver: its frame in the island view, and a press
/// that does what the click there does.
private final class IslandHitElement: NSAccessibilityElement {
    private let press: @MainActor @Sendable () -> Void

    init(
        label: String, frame: CGRect, parent: NSView,
        press: @escaping @MainActor @Sendable () -> Void
    ) {
        self.press = press
        super.init()
        setAccessibilityRole(.button)
        setAccessibilityLabel(label)
        setAccessibilityParent(parent)
        setAccessibilityFrameInParentSpace(frame)
    }

    override func accessibilityPerformPress() -> Bool {
        let press = press
        MainActor.assumeIsolated { press() }
        return true
    }
}

/// The panel never becomes key, so every click on a row is a first click.
private final class IslandListHost: NSHostingView<IslandListView> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// Where the scene is drawn, in the island view's points whatever part of it the canvas
/// covers.
private final class IslandCanvas: NSView {
    var draws: (CGContext) -> Void = { _ in }

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layerContentsRedrawPolicy = .onSetNeedsDisplay
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) is not supported")
    }

    override var isFlipped: Bool { true }
    override var isOpaque: Bool { false }

    override func hitTest(_ point: NSPoint) -> NSView? { nil }

    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.clear(bounds)
        context.translateBy(x: -frame.minX, y: -frame.minY)
        draws(context)
    }
}
