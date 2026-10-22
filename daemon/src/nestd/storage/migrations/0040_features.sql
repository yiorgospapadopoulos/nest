-- B103: Settings > Features. Each device's first visit, and when it first showed a feature.

CREATE TABLE feature_visits (
    device_id TEXT PRIMARY KEY REFERENCES devices (id),
    first_visit_at TEXT NOT NULL
);

CREATE TABLE feature_seen (
    device_id TEXT NOT NULL REFERENCES devices (id),
    feature_id TEXT NOT NULL,
    first_shown_at TEXT NOT NULL,
    PRIMARY KEY (device_id, feature_id)
);
