import Foundation

// A working pixie's sprite hops and blinks (B48), step for step as on the iPhone: steps of
// 170 ms, lifted one cell on the middle two of every four, blinking while lifted on every
// third hop. A resting sprite holds still. A blink draws its eye cells in its colour (B89).

/// A cell of a mascot's grid: `x` from the left, `y` from the top.
public struct GridCell: Sendable, Hashable {
    public let x: Int
    public let y: Int

    public init(x: Int, y: Int) {
        self.x = x
        self.y = y
    }

    /// The cells of a grid holding `code`, row by row from the top.
    public static func all(_ code: Character, in rows: [String]) -> [GridCell] {
        rows.enumerated().flatMap { y, row in
            row.enumerated().filter { $0.element == code }.map { GridCell(x: $0.offset, y: y) }
        }
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

/// What a sprite's cells are drawn in: `#RRGGBB` and an opacity.
public struct SpriteInk: Sendable, Hashable {
    public let hex: String
    public let opacity: Double

    public init(hex: String, opacity: Double = 1) {
        self.hex = hex
        self.opacity = opacity
    }
}

/// The cells of a sprite drawn in one ink.
public struct SpriteLayer: Sendable, Hashable {
    public let ink: SpriteInk
    public let cells: [GridCell]
}

/// The tones of a sprite's cell codes, all from the pixie's one colour (B89), as on the
/// iPhone: "#" the colour, "+" shade, "o" light, "*" wing, "e" eyes and "k" ink marks in
/// the ink. A blink draws the eyes in the colour.
public enum SpriteTones {
    /// The codes that are drawn, in the order their layers are.
    static let codes: [Character] = ["#", "+", "o", "*", "e", "k"]

    /// The ink of a cell code in a pixie colour; nil for an empty cell or an unknown code.
    /// A colour that is not `#RRGGBB` reads as the standard violet.
    public static func ink(of code: Character, color: String, blinking: Bool) -> SpriteInk? {
        let body = PixieColor.rgba(color) ?? PixieColor.rgba(PixieColor.standard)!
        switch code {
        case "#": return SpriteInk(hex: hex(body))
        case "+": return mix(body, MascotTones.shade)
        case "o": return mix(body, MascotTones.light)
        case "*": return mix(body, MascotTones.wing)
        case "e": return SpriteInk(hex: blinking ? hex(body) : MascotTones.ink)
        case "k": return SpriteInk(hex: MascotTones.ink)
        default: return nil
        }
    }

    /// The colour moved toward the tone's colour by its amount, per channel of 0 to 255,
    /// rounded.
    private static func mix(_ color: RGBA, _ tone: MascotTone) -> SpriteInk {
        let toward = PixieColor.rgba(tone.toward)!
        func channel(_ from: Double, _ to: Double) -> Double {
            let start = (from * 255).rounded()
            return (start + ((to * 255).rounded() - start) * tone.amount).rounded() / 255
        }
        let hex = PixieColor.hex(
            red: channel(color.red, toward.red), green: channel(color.green, toward.green),
            blue: channel(color.blue, toward.blue))
        return SpriteInk(hex: hex, opacity: tone.opacity)
    }

    private static func hex(_ color: RGBA) -> String {
        PixieColor.hex(red: color.red, green: color.green, blue: color.blue)
    }
}

extension Mascot {
    /// Its drawn cells, one layer per cell code it has, in `SpriteTones`' inks.
    public func layers(color: String, blinking: Bool) -> [SpriteLayer] {
        SpriteTones.codes.compactMap { code in
            let cells = GridCell.all(code, in: rows)
            guard !cells.isEmpty else { return nil }
            return SpriteLayer(
                ink: SpriteTones.ink(of: code, color: color, blinking: blinking)!, cells: cells)
        }
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
