-- Web push subscriptions, one per browser install. Each belongs to the paired device that
-- registered it; revoking the device deletes them.
CREATE TABLE push_subscriptions (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices (id),
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_success_at TEXT,
    -- Consecutive failed deliveries; reset by a success.
    failures INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX push_subscriptions_device_id ON push_subscriptions (device_id);
