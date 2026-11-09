-- Computer use (B150): the targets the user let the chat use, as a JSON list of keys.
ALTER TABLE sessions ADD COLUMN computer_targets TEXT NOT NULL DEFAULT '[]';
