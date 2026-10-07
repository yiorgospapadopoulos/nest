import CoreGraphics

/// What dropping a dragged chat or pane at a point of the workspace does.
public enum DropZone: Sendable, Hashable {
    /// The workspace is empty: the chat opens there.
    case open
    case split(DropSide)
    /// Four chats are open: the dragged chat takes this pane.
    case replace
    /// A pane dragged by its header trades places with this one.
    case swap
    case none

    public enum Kind: Sendable, Hashable {
        /// A chat from the sidebar.
        case chat
        /// An open pane, dragged by its header.
        case pane
    }

    /// The pane under the pointer.
    public struct Target: Sendable, Hashable {
        /// The pane shows the dragged chat itself.
        public var isDraggedChat: Bool
        public var draggedIsOpen: Bool
        public var openCount: Int

        public init(isDraggedChat: Bool, draggedIsOpen: Bool, openCount: Int) {
            self.isDraggedChat = isDraggedChat
            self.draggedIsOpen = draggedIsOpen
            self.openCount = openCount
        }
    }

    /// The zone at `point` of a pane of `size`; `target` is nil for the empty workspace.
    /// The top and bottom quarters split vertically, the middle splits left or right.
    public static func zone(at point: CGPoint, in size: CGSize, kind: Kind, target: Target?)
        -> DropZone
    {
        guard let target else { return .open }
        if target.isDraggedChat {
            return .none
        }
        if kind == .pane {
            return .swap
        }
        if !target.draggedIsOpen && target.openCount >= WorkspaceLayout.maximumPanes {
            return .replace
        }
        let x = point.x / size.width
        let y = point.y / size.height
        if y < 0.26 {
            return .split(.top)
        }
        if y > 0.74 {
            return .split(.bottom)
        }
        return .split(x < 0.5 ? .left : .right)
    }

    public var label: String {
        switch self {
        case .open: "Open here"
        case .split(.left): "Split left"
        case .split(.right): "Split right"
        case .split(.top): "Split top"
        case .split(.bottom): "Split bottom"
        case .replace: "Replace this chat"
        case .swap: "Swap panes"
        case .none: ""
        }
    }

    /// The part of the pane the drop highlight covers.
    public func highlight(in size: CGSize) -> CGRect {
        let whole = CGRect(origin: .zero, size: size)
        switch self {
        case .open, .replace, .swap: return whole
        case .none: return .zero
        case .split(let side):
            let half = CGSize(width: size.width / 2, height: size.height / 2)
            switch side {
            case .left: return CGRect(x: 0, y: 0, width: half.width, height: size.height)
            case .right: return CGRect(x: half.width, y: 0, width: half.width, height: size.height)
            case .top: return CGRect(x: 0, y: 0, width: size.width, height: half.height)
            case .bottom:
                return CGRect(x: 0, y: half.height, width: size.width, height: half.height)
            }
        }
    }
}
