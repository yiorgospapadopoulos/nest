-- B108: each folder a chat works in (a worktree, or a repo's main checkout) keeps a block
-- of ports for its life: block `block` is `[ports] start + block * size` and the `size - 1`
-- ports after it. Freed when Nest removes the worktree, or when the repo is removed.
CREATE TABLE port_blocks (
    folder TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    block INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
