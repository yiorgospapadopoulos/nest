/// A rectangle in points, top-left origin, as the Accessibility API gives it.
public struct Rect: Sendable, Equatable {
    public var x: Double
    public var y: Double
    public var width: Double
    public var height: Double

    public init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }

    /// The same rectangle measured from `origin`, such as a window's top-left corner.
    public func relative(to origin: Rect) -> Rect {
        Rect(x: x - origin.x, y: y - origin.y, width: width, height: height)
    }

    public var json: JSONValue {
        ["x": .double(x), "y": .double(y), "width": .double(width), "height": .double(height)]
    }
}

/// The largest side of a screenshot the helper sends.
public let screenshotMaxSide = 1280

/// The size an image is scaled down to so that its long side is at most `maxSide`. Smaller
/// images keep their size.
public func fittedSize(width: Int, height: Int, maxSide: Int = screenshotMaxSide) -> (
    width: Int, height: Int
) {
    let longSide = max(width, height)
    guard longSide > maxSide, width > 0, height > 0 else { return (width, height) }
    let scale = Double(maxSide) / Double(longSide)
    return (
        max(1, Int((Double(width) * scale).rounded())),
        max(1, Int((Double(height) * scale).rounded()))
    )
}

/// The screen point of a click at (`x`, `y`) points inside a window, or an error when the
/// point is outside it.
public func screenPoint(in window: Rect, x: Double, y: Double) throws(HelperError) -> (
    x: Double, y: Double
) {
    guard x >= 0, y >= 0, x < window.width, y < window.height else {
        throw HelperError(
            .badRequest,
            "(\(x), \(y)) is outside the window (\(window.width) by \(window.height) points)")
    }
    return (window.x + x, window.y + y)
}
