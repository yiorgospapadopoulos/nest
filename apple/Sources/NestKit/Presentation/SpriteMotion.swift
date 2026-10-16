import Foundation

// A working pixie's sprite hops and blinks (B48), step for step as on the iPhone: steps of
// 170 ms, lifted one cell on the middle two of every four, blinking while lifted on every
// third hop. A resting sprite holds still.

/// A cell of a mascot's grid: `x` from the left, `y` from the top.
public struct GridCell: Sendable, Hashable {
    public let x: Int
    public let y: Int

    public init(x: Int, y: Int) {
        self.x = x
        self.y = y
    }
}

/// How a sprite looks at one moment of its hop.
public struct SpriteFrame: Sendable, Hashable {
    /// Drawn one cell above its place.
    public let lifted: Bool
    public let blinking: Bool

    public init(lifted: Bool, blinking: Bool) {
        self.lifted = lifted
        self.blinking = blinking
    }

    public static let rest = SpriteFrame(lifted: false, blinking: false)
}

public enum SpriteMotion {
    /// One step, in seconds.
    public static let step = 0.17
    /// Three hops of four steps, in milliseconds: phases spread across it, so blinks
    /// differ too.
    static let cycle: UInt32 = 2040

    /// The frame at a time in milliseconds on a sprite's own clock (its phase added).
    public static func frame(at milliseconds: Double) -> SpriteFrame {
        let step = wrapped(milliseconds / 170, 4)
        let hop = wrapped(milliseconds / 680, 3)
        let lifted = step == 1 || step == 2
        return SpriteFrame(lifted: lifted, blinking: lifted && hop == 2)
    }

    /// A stable offset of a sprite's clock, in milliseconds, from a key such as the
    /// pixie's id: FNV-1a of its UTF-16 units, so sprites do not hop in lockstep and every
    /// launch and client agrees.
    public static func phase(of key: String) -> Double {
        var hash: UInt32 = 2_166_136_261
        for unit in key.utf16 {
            hash = (hash ^ UInt32(unit)) &* 16_777_619
        }
        return Double(hash % cycle)
    }

    private static func wrapped(_ value: Double, _ count: Int) -> Int {
        let whole = Int(value.rounded(.down))
        return (whole % count + count) % count
    }
}

/// What a blink changes in a mascot's grid.
public enum MascotBlink: Sendable, Hashable {
    /// Its eyes, small holes, are filled.
    case fill(Set<GridCell>)
    /// Its eyes are lone filled cells, and they go.
    case hide(Set<GridCell>)
}

extension Mascot {
    /// What a blink changes in its grid.
    public var blink: MascotBlink { Self.blink(of: rows) }

    /// The eyes of a grid: of the empty regions (cells joined side by side) that do not
    /// touch the edge and have at most six cells, those starting on the highest row, so
    /// mouths and spots below stay; with none, its lone filled cells.
    static func blink(of rows: [String]) -> MascotBlink {
        let grid = rows.map { Array($0) }
        let holes = Self.holes(grid).filter { $0.count <= 6 }
        let tops = holes.map { $0.map(\.y).min()! }
        if let top = tops.min() {
            return .fill(Set(zip(holes, tops).filter { $0.1 == top }.flatMap(\.0)))
        }
        return .hide(Set(Self.cells(grid, "#").filter { Self.neighbours($0, grid, "#").isEmpty }))
    }

    /// Its grid as `rows`, with the blink applied while `blinking`.
    public func rows(blinking: Bool) -> [String] {
        guard blinking else { return rows }
        let (cells, mark): (Set<GridCell>, Character) =
            switch blink {
            case .fill(let cells): (cells, "#")
            case .hide(let cells): (cells, ".")
            }
        return rows.enumerated().map { y, row in
            String(row.enumerated().map { cells.contains(GridCell(x: $0, y: y)) ? mark : $1 })
        }
    }

    private static func cells(_ grid: [[Character]], _ mark: Character) -> [GridCell] {
        grid.enumerated().flatMap { y, row in
            row.indices.filter { row[$0] == mark }.map { GridCell(x: $0, y: y) }
        }
    }

    private static func neighbours(_ cell: GridCell, _ grid: [[Character]], _ mark: Character)
        -> [GridCell]
    {
        [(1, 0), (-1, 0), (0, 1), (0, -1)]
            .map { GridCell(x: cell.x + $0.0, y: cell.y + $0.1) }
            .filter {
                grid.indices.contains($0.y) && grid[$0.y].indices.contains($0.x)
                    && grid[$0.y][$0.x] == mark
            }
    }

    /// The empty regions that do not touch the edge.
    private static func holes(_ grid: [[Character]]) -> [[GridCell]] {
        var seen: Set<GridCell> = []
        var holes: [[GridCell]] = []
        for start in cells(grid, ".") where !seen.contains(start) {
            var region: [GridCell] = []
            var queue = [start]
            seen.insert(start)
            while let cell = queue.popLast() {
                region.append(cell)
                for next in neighbours(cell, grid, ".") where seen.insert(next).inserted {
                    queue.append(next)
                }
            }
            let edge = region.contains {
                $0.x == 0 || $0.y == 0 || $0.y == grid.count - 1 || $0.x == grid[$0.y].count - 1
            }
            if !edge {
                holes.append(region)
            }
        }
        return holes
    }
}

extension SessionState {
    /// A pixie's chat in this state is working: its sprite hops.
    public var isWorking: Bool { self == .starting || self == .running }
}

/// A cell of a team's icon: a member's sprite, hopping while its call runs.
public struct TeamIconCell: Sendable, Hashable {
    public let pixie: Pixie
    public let working: Bool
    /// The pixie's id and the cell's index, so copies of one pixie keep their own clocks.
    public let phaseKey: String

    public init(pixie: Pixie, working: Bool, index: Int) {
        self.pixie = pixie
        self.working = working
        phaseKey = "\(pixie.id)#\(index)"
    }
}

/// A team's icon: a two by two grid of its members' sprites (B48).
public enum TeamIcon {
    /// Four cells from members in order: four or more give the first four, fewer repeat
    /// in order (A A A A, A B A B, A B C A). Empty for none.
    public static func fill<Member>(_ members: [Member]) -> [Member] {
        guard !members.isEmpty else { return [] }
        return (0..<4).map { members[$0 % members.count] }
    }

    /// The icon of a team a chat called: its leader, then its other known members in the
    /// team's order.
    public static func cells(of entry: ChatPixieEntry, pixies: [Pixie]) -> [TeamIconCell] {
        let ordered = entry.members.filter(\.leader) + entry.members.filter { !$0.leader }
        let known = ordered.compactMap { member in
            pixies.first { $0.id == member.pixieID }.map { ($0, member.state == .running) }
        }
        return fill(known).enumerated().map {
            TeamIconCell(pixie: $1.0, working: $1.1, index: $0)
        }
    }
}
