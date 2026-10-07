import Foundation

/// JSON coding as the daemon speaks it: snake_case keys spelled out per model, and
/// ISO 8601 dates with or without fractional seconds.
public enum HarnessJSON {
    static let dateStyle = Date.ISO8601FormatStyle(includingFractionalSeconds: true)

    public static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let text = try container.decode(String.self)
            guard let date = try? dateStyle.parse(text) else {
                throw DecodingError.dataCorruptedError(
                    in: container, debugDescription: "not an ISO 8601 date: \(text)")
            }
            return date
        }
        return decoder
    }

    public static var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(date.formatted(dateStyle))
        }
        return encoder
    }
}

/// A string enum that decodes values it does not know as `unknown`, so a newer daemon
/// cannot break decoding.
public protocol UnknownSafeEnum: RawRepresentable, Codable, Sendable, Hashable
where RawValue == String {
    static var unknown: Self { get }
}

extension UnknownSafeEnum {
    public init(from decoder: any Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = Self(rawValue: raw) ?? .unknown
    }
}

/// A calendar day such as `2026-10-06`, as the daemon sends plain dates.
public struct CalendarDay: Decodable, Sendable, Hashable, Comparable {
    public let year: Int
    public let month: Int
    public let day: Int

    public init(year: Int, month: Int, day: Int) {
        self.year = year
        self.month = month
        self.day = day
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        let text = try container.decode(String.self)
        let parts = text.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else {
            throw DecodingError.dataCorruptedError(
                in: container, debugDescription: "not a date: \(text)")
        }
        self.init(year: parts[0], month: parts[1], day: parts[2])
    }

    public var description: String {
        let month = month < 10 ? "0\(month)" : "\(month)"
        let day = day < 10 ? "0\(day)" : "\(day)"
        return "\(year)-\(month)-\(day)"
    }

    public static func < (lhs: CalendarDay, rhs: CalendarDay) -> Bool {
        (lhs.year, lhs.month, lhs.day) < (rhs.year, rhs.month, rhs.day)
    }
}
