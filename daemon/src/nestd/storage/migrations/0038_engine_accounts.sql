-- B98: several subscriptions per engine, one active at a time. The first account of each
-- engine is the user's own login; an added one has its own profile folder. The status
-- columns keep the last answer the engine gave about the account.
CREATE TABLE engine_accounts (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    name TEXT,
    profile TEXT,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    email TEXT,
    plan TEXT,
    signed_in INTEGER,
    checked_at TEXT
);

INSERT INTO engine_accounts (id, provider, position, created_at)
VALUES
    ('claude-main', 'claude', 0, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    ('codex-main', 'codex', 0, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));

CREATE TABLE active_accounts (
    provider TEXT PRIMARY KEY,
    account_id TEXT NOT NULL
);

INSERT INTO active_accounts (provider, account_id)
VALUES ('claude', 'claude-main'), ('codex', 'codex-main');

-- Usage windows are kept per account; every earlier one is the first account's.
CREATE TABLE account_usage_limits (
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    name TEXT NOT NULL,
    utilization REAL NOT NULL,
    resets_at TEXT,
    updated_at TEXT NOT NULL,
    minutes INTEGER,
    PRIMARY KEY (account_id, name)
);

INSERT INTO account_usage_limits
    (account_id, provider, name, utilization, resets_at, updated_at, minutes)
    SELECT provider || '-main', provider, name, utilization, resets_at, updated_at, minutes
    FROM usage_limits;

DROP TABLE usage_limits;

-- The resets a Codex account has banked, with its usage; `credits` (JSON) once read.
CREATE TABLE banked_resets (
    account_id TEXT PRIMARY KEY,
    available INTEGER NOT NULL,
    credits TEXT,
    updated_at TEXT NOT NULL
);

ALTER TABLE account_usage_limits RENAME TO usage_limits;
