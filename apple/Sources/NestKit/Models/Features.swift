import Foundation

/// Settings > Features (B103): what makes Nest different, by area, as `GET /api/features`
/// answers it for this device.
public struct FeaturesCatalog: Codable, Sendable, Hashable {
    public var groups: [FeatureGroup]
    /// How many features are new on this device.
    public var newCount: Int

    public init(groups: [FeatureGroup], newCount: Int) {
        self.groups = groups
        self.newCount = newCount
    }

    /// Every group's features together.
    public var total: Int { groups.reduce(0) { $0 + $1.features.count } }

    enum CodingKeys: String, CodingKey {
        case groups
        case newCount = "new_count"
    }
}

public struct FeatureGroup: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var name: String
    public var features: [Feature]

    public init(id: String, name: String, features: [Feature]) {
        self.id = id
        self.name = name
        self.features = features
    }

    public var newCount: Int { features.count(where: \.isNew) }
}

public struct Feature: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var name: String
    /// One or two sentences; `backticks` mark inline code.
    public var text: String
    /// Where to find it in the app, such as "Sidebar".
    public var place: String
    /// Plain dates, `YYYY-MM-DD`.
    public var added: String
    public var changed: String?
    public var block: String
    public var isNew: Bool

    public init(
        id: String, name: String, text: String, place: String, added: String,
        changed: String? = nil, block: String, isNew: Bool = false
    ) {
        self.id = id
        self.name = name
        self.text = text
        self.place = place
        self.added = added
        self.changed = changed
        self.block = block
        self.isNew = isNew
    }

    /// The text as plain and code runs.
    public var parts: [InlineCode] { InlineCode.parts(text) }

    enum CodingKeys: String, CodingKey {
        case id, name, text, added, changed, block
        case place = "where"
        case isNew = "new"
    }
}

/// `POST /api/features/seen`: the features this device shows.
struct FeaturesSeenRequest: Encodable {
    let ids: [String]
}
