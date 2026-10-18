-- Pixies redrawn as fairies (B89): every stored mascot takes its new name, in the
-- pixies and in the stored `pixie.updated` events a client may replay. The column has no
-- default; new pixies are bluebells.
CREATE TEMP TABLE mascot_renames (old TEXT PRIMARY KEY, new TEXT NOT NULL);
INSERT INTO mascot_renames (old, new) VALUES
    ('invader', 'frost'),
    ('ghost', 'brook'),
    ('cat', 'bluebell'),
    ('owl', 'moth'),
    ('robot', 'star'),
    ('frog', 'dragonfly'),
    ('mushroom', 'rose'),
    ('bunny', 'nightshade'),
    ('crab', 'firefly'),
    ('sprout', 'sprig');

UPDATE pixies
SET mascot = (SELECT new FROM mascot_renames WHERE old = pixies.mascot)
WHERE mascot IN (SELECT old FROM mascot_renames);

UPDATE events
SET payload = json_set(
    payload,
    '$.pixie.mascot',
    (SELECT new FROM mascot_renames WHERE old = json_extract(events.payload, '$.pixie.mascot'))
)
WHERE type = 'pixie.updated'
    AND json_extract(payload, '$.pixie.mascot') IN (SELECT old FROM mascot_renames);

DROP TABLE mascot_renames;
