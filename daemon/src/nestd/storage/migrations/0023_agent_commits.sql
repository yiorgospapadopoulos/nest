-- Chats commit, push and open pull requests when the user asks, as in the terminal (B58):
-- a commit the agent makes is no longer a violation to flag.
ALTER TABLE sessions DROP COLUMN git_violation;
