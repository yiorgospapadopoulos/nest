import Foundation

public enum ReviewGuideState: String, UnknownSafeEnum {
    case writing, ready, failed
    case unknown
}

/// A review guide an agent wrote for the pull request, saved as an artifact (B149).
public struct ReviewGuide: Codable, Sendable, Hashable {
    public var state: ReviewGuideState
    /// The pull request's head commit it was written for.
    public var headSHA: String?
    public var artifactID: String?
    public var error: String?
    /// The comment on the pull request, once posted there.
    public var commentURL: String?

    enum CodingKeys: String, CodingKey {
        case state, error
        case headSHA = "head_sha"
        case artifactID = "artifact_id"
        case commentURL = "comment_url"
    }
}

/// What the pull request popover's review guide row offers.
public enum ReviewGuideRow: Sendable, Hashable {
    case write
    case writing
    case failed(String?)
    /// `outdated` when the pull request has new commits since it was written.
    case ready(artifact: String, commentURL: String?, outdated: Bool)

    public init(_ guide: ReviewGuide?, pr: PullRequest) {
        switch guide?.state {
        case .writing: self = .writing
        case .failed: self = .failed(guide?.error)
        case .ready:
            if let guide, let artifact = guide.artifactID {
                self = .ready(
                    artifact: artifact, commentURL: guide.commentURL,
                    outdated: guide.headSHA != pr.headSHA)
            } else {
                self = .write
            }
        case .unknown, nil: self = .write
        }
    }
}
