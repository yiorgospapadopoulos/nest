-- Pixie teams (B40): a name, an `@` handle sharing the namespace of pixie slugs, and a
-- leader among the members. Each pixie is in one team or none.
CREATE TABLE pixie_teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    handle TEXT NOT NULL UNIQUE,
    -- NULL only while the team has no members.
    leader_id TEXT REFERENCES pixies (id),
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

ALTER TABLE pixies ADD COLUMN team_id TEXT REFERENCES pixie_teams (id);
CREATE INDEX pixies_team_id ON pixies (team_id);
