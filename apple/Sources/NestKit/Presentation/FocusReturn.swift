import Foundation

/// Where the keyboard was before each layer over the window opened, to give it back when
/// that layer closes. A layer opened again while it is open keeps what it saved first, so
/// going from one sheet straight to another still returns to where the user started.
public struct FocusReturn<Target: AnyObject> {
    /// The layers over the window, Settings under the sheets.
    public enum Layer: Hashable, Sendable {
        case settings, sheet
    }

    private struct Saved {
        weak var target: Target?
    }

    private var saved: [Layer: Saved] = [:]

    public init() {}

    public mutating func opened(_ layer: Layer, from target: Target?) {
        guard saved[layer] == nil else { return }
        saved[layer] = Saved(target: target)
    }

    /// What had the keyboard before the layer opened, if it is still there.
    public mutating func closed(_ layer: Layer) -> Target? {
        saved.removeValue(forKey: layer)?.target
    }
}
