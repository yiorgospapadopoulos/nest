import os
import subprocess
from pathlib import Path
from typing import cast

import pytest
from claude_agent_sdk.types import (
    HookContext,
    HookInput,
    PreToolUseHookInput,
    UserPromptSubmitHookInput,
)

from nestd.providers.git_guard import (
    DENY_REASON,
    GIT_WRITE_RULES,
    block_git_writes,
    block_subagent_git_writes,
    is_git_write,
    tool_writes,
)
from nestd.providers.push_block import NO_PUSH_ENV

BLOCKED = [
    "cd x && git push origin main",
    "cd a && cd b && git push",
    "cd x; git push && grep a b",
    "cd $(git push) && grep a b",
    'cd "$(git push)" && grep a b',
    "cd `git push` && grep a b",
    'grep "git push" b | sh',
    'cd x && grep "git push" b | sh',
    'echo "git push" | head -1 | sh',
    'echo "git push" | sh',
    'grep "git push" . | tail -5; git push',
    'cd x && echo "git push" > y.sh',
    "git push -m 'x'",
    "git push",
    "git push origin main --force",
    "cd sub && git push --allow-empty -m b",
    "true; git push",
    "ls | xargs git push -m x",
    "sh -c 'git push --allow-empty -m c'",
    'bash -lc "git push origin HEAD"',
    "git -c user.name=x push --allow-empty -m d",
    "git -C /tmp/repo push",
    "git --no-pager -c a=b -C dir push",
    "git --git-dir /x/.git --work-tree /x push -am y",
    "git --git-dir=/x/.git push",
    "/usr/bin/git push -m x",
    "env GIT_AUTHOR_NAME=x git push",
    "sudo git push",
    "git 'push' -m quoted",
    "echo $(git push -m inline)",
    "git\tpush",
    "git send-pack origin HEAD",
    "gh pr create --fill",
    "gh  pr   merge 12 --squash",
    "cd x && gh pr create",
    # Quoted and escaped arguments.
    'git -C "my dir" push -m x',
    'git -c user.name="A B" push -m x',
    '"git" push -m x',
    "git -C 'dir with space' --no-pager push",
    'git --git-dir "/a b/.git" --work-tree "/a b" push',
    "g\\it push",
    "g\"i\"t pu'sh'",
    "git pu\\sh -m x",
    "git \\\n  push",
    'git push -m "unbalanced',
    # Environment prefixes and wrappers.
    "GIT_DIR=x git push",
    'FOO="a b" git push -m x',
    "command git push",
    "env -i PATH=/usr/bin git push",
    "exec git push",
    "timeout 60 git push",
    "nohup git push &",
    "nice -n 5 git push -m x",
    "xargs -I{} git -C {} push",
    "find . -name .git -execdir git push \\;",
    # Paths to git, and case on a case-insensitive file system.
    "'/usr/bin/git' push",
    "/opt/homebrew/bin/GIT push",
    "git PUSH -m x",
    "git Push",
    "/usr/libexec/git-core/git-push -m x",
    "git-push origin main",
    # Separators, subshells and groups.
    "(git push)",
    "{ git push; }",
    "git status;git push",
    "git status&&git push",
    "git status||git push",
    "git status|git push",
    "git status & git push",
    "git status\ngit push",
    "git log x#; git push",
    "f() { git push -m x; }; f",
    "if true; then git push; fi",
    "for r in a b; do git -C $r push; done",
    "git -C ';' push",
    # Shells and strings run as commands.
    "sh -c \"git -C 'a b' push\"",
    "bash -c 'cd \"a b\" && git push -m x'",
    "zsh -c \"eval 'git push'\"",
    'eval "git push"',
    "env -S 'git push'",
    "python3 -c \"import subprocess; subprocess.run(['git', 'push'])\"",
    "printf 'git push' | sh",
    "echo git push | bash -s",
    "sh <<E\ngit push\nE",
    "sh <<< 'git push'",
    "cat <<E | sh\ngit push\nE",
    "python3 <<E\nimport os; os.system('git push')\nE",
    "cat <<E | python\nimport os; os.system('gh pr create')\nE",
    "bash <(echo git push)",
    "/bin/zsh -lc 'git push origin main'",
    "bash -lc 'echo $(git push)'",
    "ssh host 'cd x && git push'",
    'echo "$(git push)"',
    'git commit -m "run `git push`"',
    # Words built at run time.
    "$(echo git) push",
    "G=git; $G push",
    "`echo git` push",
    "x=`git push`",
    "cmd=push; git $cmd",
    "git $(echo push) -m x",
    "$(which git) push",
    "`which git` push",
    "$(echo git push)",
    'C="git push"; $C',
    'C="git push"; eval "$C"',
    'C="git push"; sh -c "$C"',
    "sudo $GIT push",
    "$GH pr create",
    "A=merge; gh pr $A",
    # Aliases.
    "git -c alias.ship=push ship",
    "git -c alias.ci=push ci -m x",
    "git -c alias.CI=push ci -m x",
    "git -c 'alias.x=!git push' x",
    "git -c alias.x='!sh -c \"git push\"' x",
    "git -c alias.a=b -c alias.b=push a",
    "git --config-env=alias.x=VAR x",
    "git --config-env alias.x=VAR x",
    "git -c 'alias.x=log \"a' x",
    "git config alias.ci push",
    'git config --global alias.p "push --force"',
    # Other ways to send commits.
    "git subtree push --prefix=x origin main",
    "git send-pack origin main",
    "git http-push https://example.com/r.git main",
    # Unknown global options make the subcommand uncertain.
    "git --unknown-option x push",
    "git -P push",
    "git --no-pager --bare -p push",
    # gh with flags before or after pr.
    "gh -R o/r pr create",
    "gh --repo o/r pr merge 1",
    "gh pr --repo o/r create --fill",
    "gh pr -R o/r merge 3",
    "gh pr --repo=o/r merge 3",
    "gh pr new",
    '"gh" pr create',
    "GH_REPO=o/r gh pr create",
    "gh pr -R ';' create",
    # gh api calls that create or merge a pull request.
    "gh api repos/o/r/pulls -f title=x -f head=y -f base=main",
    "gh api --method POST /repos/o/r/pulls",
    "gh api -X POST repos/{owner}/{repo}/pulls --input body.json",
    "gh api -X PUT repos/o/r/pulls/3/merge",
    "gh api repos/o/r/pulls/$N/merge --method=PUT -f merge_method=squash",
    "gh api repos/o/r/merges -f base=main -f head=x",
    "gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'",
    "gh api graphql -F query='mutation { createPullRequest(input: {}) { clientMutationId } }'",
    "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { actor } }'",
    "sh -c 'gh api -X PUT repos/o/r/pulls/3/merge'",
    # gh api unless it is clearly a read (D160): direct commits, ref writes, and flags hidden.
    "gh api -X PUT repos/o/r/contents/a.txt -f message=x -f content=eA==",
    "gh api repos/o/r/git/refs -f ref=refs/heads/x -f sha=abc",
    "gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc",
    "gh api repos/o/r/merge-upstream -f branch=main",
    "gh api -X POST repos/o/r/pulls/3/comments -f body=x",
    "gh api -XPUT repos/o/r/contents/a.txt",
    "gh api -X=PUT repos/o/r/contents/a.txt",
    "gh api -iX PUT repos/o/r/contents/a.txt",
    "gh api -iXPUT repos/o/r/contents/a.txt",
    "gh api -if a=b repos/o/r/git/refs",
    "gh api -fa=b repos/o/r/git/refs",
    "gh api repos/o/r/git/refs --raw-field a=b",
    "gh api repos/o/r/git/refs --input=b.json",
    "gh api -X GET -X PUT repos/o/r/contents/a.txt",
    "gh api -X $M repos/o/r/contents/a.txt",
    'gh api "$URL"',
    "gh api $ARGS",
    "gh api $(cat args)",
    "gh api repos/o/r/pulls/$(cat n)/merge -X PUT",
    "gh api repos/o/r/pulls/`cat n`/merge -X PUT",
    "gh $A -X PUT repos/o/r/contents/a.txt",
    "gh $(echo api) -X PUT repos/o/r/contents/a.txt",
    "gh api --jq graphql repos/o/r/git/refs -f a=b",
    "gh api /graphql -f query=x",
    # The path holds no meaning: flags decide (report item 8).
    "gh api -X PUT repos/o/r/pulls/3/merge -f commit_title=graphql",
    "gh api repos/o/graphql-tools/pulls -f title=x",
    "gh api repos/o/r/pull%73 -f title=x",
    # gh api graphql that may write.
    "gh api graphql -f query='mutation { createCommitOnBranch(input: {}) { clientMutationId } }'",
    "gh api graphql -f query='MUTATION { mergeBranch(input: {}) { clientMutationId } }'",
    "gh api graphql -F query=@q.graphql",
    "gh api graphql --input q.json",
    'gh api graphql -f query="$Q"',
    'gh api graphql -f query="$(cat q.graphql)"',
    "gh api graphql -f query=`cat q.graphql`",
    # The token, and other gh commands that write or run later.
    "gh auth token",
    'curl -H "Authorization: token $(gh auth token)" https://api.github.com/x',
    # Other ways to the token or a stored password (B159 R03).
    "gh auth status --show-token",
    "gh auth status -t",
    "gh auth status -at",
    "gh auth status --hostname github.com --show-token=true",
    "gh auth git-credential get",
    "printf 'protocol=https\\nhost=github.com\\n' | gh auth git-credential get",
    "printf 'protocol=https\\nhost=github.com\\n' | git credential fill",
    "git -C repo credential fill",
    "git credential get",
    "git credential-osxkeychain get",
    "git-credential-osxkeychain get",
    "/usr/local/bin/git-credential-manager get",
    "sh -c 'echo host=github.com | git credential fill'",
    # An alias set first, to run the helper later (B159 recheck 1).
    "git config alias.c credential",
    "git config --global alias.C 'credential fill'",
    "git config alias.k credential-osxkeychain",
    "git config alias.k '!git credential fill'",
    "git config alias.k '!git-credential-osxkeychain get'",
    # Config from the environment can define an alias or undo the push block (recheck 2 F).
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push git p",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.c GIT_CONFIG_VALUE_0=credential git c fill",
    "GIT_CONFIG_PARAMETERS=\"'alias.p=push'\" git p",
    "env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push git p",
    "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push; git p",
    "export GIT_CONFIG_PARAMETERS=\"'alias.p=push'\"\ngit -C repo p",
    "GIT_CONFIG_KEY_0=remote.origin.pushurl git status",
    "sh -c 'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push git p'",
    "gh repo sync",
    "gh repo sync o/r --force",
    "gh alias set zz 'pr merge'",
    "gh alias set --shell zz 'gh pr create --fill'",
    "gh alias import aliases.yml",
    "A=merge; gh pr $A 1",
    # An apostrophe in a comment pairs with the next one (report item 1).
    "# Let's ship it\ngit push origin main\n# Don't forget the tag",
    "# Let's ship it\ngh pr create --fill\n# Don't forget the tag",
    "# Let's ship it\ngh pr merge 1 --squash\n# Don't forget the tag",
    # git or gh run inside another command (report item 3).
    "git submodule foreach 'git push origin main'",
    "git rebase -x 'gh pr merge 1' HEAD~1",
    "git bisect run sh -c 'git push origin main'",
    "git filter-branch --tree-filter 'git push origin main'",
    "git -c core.pager='git push origin main' log",
    "trap 'gh pr merge 1' EXIT",
    "awk 'BEGIN{system(\"git push\")}'",
    "osascript -e 'do shell script \"git push\"'",
    "tcsh -c 'git push origin main'",
    # Text in quotes hiding a real command (report item 4).
    "echo \"don't $(gh pr merge 1 --admin) won't\"",
    'echo "<<E"\ngit push origin main\nE',
    "# <<E\ngit push origin main\nE",
    "cat <<E |\ngit push origin main\nE\nsh",
    'eval "$(cat <<E\ngit push origin main\nE\n)"',
    "source /dev/stdin <<E\ngit push origin main\nE",
    "$SHELL <<E\ngit push origin main\nE",
    "python3 /dev/stdin <<E\nimport os; os.system('git push')\nE",
    "python3 -c \"$(cat <<E\nimport os; os.system('git push')\nE\n)\"",
    "source /dev/stdin <<< 'git push origin main'",
    # Words built at run time (report item 5).
    "g$()h pr merge 1",
    "g$()it push origin main",
    "$'\\x67it' push",
    'C="git push origin main"; sh -c "$C" x',
    'C="git push origin main"; eval "$C || true"',
    'C="git push origin main"; python3 -c "$C"',
    'C="git push origin main"; exec $C',
    'C="git push origin main"; env $C',
    'C="git push origin main"; X=1 $C',
    'C="git push origin main"; if true; then $C; fi',
    'C="gh pr merge 1 --admin"; exec $C',
    "echo git push | sh -o errexit",
    "echo git push | sh /dev/stdin",
    "echo git push | xargs -I{} sh -c '{}'",
    "echo git push | tee >(sh)",
    # Lines that look harmless and are not.
    "grep x src; git push",
    "grep x src && git push",
    "grep x src | sh -c 'git push'",
    "grep x src\ngit push",
    "echo hi & git push",
    "echo hi > x; git push",
    'echo "git push" | sh',
    'echo "git push" > ship.sh',
    'grep "$(git push)" src',
    'rg --pre "git push" x',
    'rg --p""re="git push" x',
    "bash -lc 'grep x; git push'",
    "bash -lc 'echo hi' && git push",
    "docker push a; git push",
    "docker push $(git push)",
    "docker push `git push`",
    "docker push ${A:-$(git push)}",
    "docker push a git push",
    "docker push $IMAGE && git push",
    "/bin/zsh -lc 'docker push $IMAGE; git push'",
    "/bin/zsh -lc 'docker push $(git push)'",
    # Commit messages from a heredoc that are not what they look like.
    "git commit -m \"$(cat <<'EOF'\nx\nEOF\ngit push\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF\n)\"\ngit push",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF\n)\"; git push",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF\n)\" && git push",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF\n)\" ; gh pr merge 1",
    "git add -A && git commit -m \"$(cat <<'EOF'\nfix git push\nEOF\n)\" && git push",
    "git push && git commit -m \"$(cat <<'EOF'\nx\nEOF\n)\"",
    'git commit -m "$(cat <<EOF\n$(git push)\nEOF\n)"',
    'git commit -m "$(cat <<EOF\nfix git push\nEOF\n)"',
    'git commit -m "$(cat <<"EOF"\nfix git push\nEOF\n)"',
    "git commit -m \"$(cat <<'EOF'; git push\nx\nEOF\n)\"",
    "git commit -m \"$(git push; cat <<'EOF'\nx\nEOF\n)\"",
    "git commit --amend=x -m \"$(cat <<'EOF'\nx\nEOF\n)\" git push",
    # bash 3.2 ends the `$(` at an unmatched `)`, even in the heredoc, and runs what follows.
    'git commit -m "$(cat <<\'EOF\'\na) "; git push origin main; echo "\nEOF\n)"',
    "git commit -m \"$(cat <<'EOF'\n' ( ' ) \"; git push origin main; echo \"\nEOF\n)\"",
    'git commit -m "$(cat <<\'EOF\'\n\\(a) "; git push origin main; echo "\nEOF\n)"',
    'git commit -m "$(cat <<\'EOF\'\n# (a\n) "; git push origin main; echo "\nEOF\n)"',
    # Accepted false refusals: only the plainly harmless lines pass.
    "cat <<E > n.md\ngit push\nE",
    "cat > ship.sh <<'EOF'\ngit push\nEOF",
    'echo "$X git push"',
    'git commit -m "fix git push"',
    "printf 'git push'",
    'git stash push -m "$MSG"',
    "docker push $IMAGE --quiet",
]

ALLOWED = [
    'cd repo && grep -rn "git push" .',
    'cd "/tmp/a dir" && rg "gh pr create" .',
    'grep -rn "git push" src | head -20',
    'cd repo && grep -rn "git push" . 2>/dev/null | head -n 5',
    'rg "git push" . | wc -l',
    "git status",
    "git diff",
    "git log --grep commit",
    "git log --oneline -- push.py",
    "git diff src/commit.ts",
    "git show HEAD:commit/handler.py",
    "git stash push -m wip",
    'git stash push -m "wip push"',
    "git lfs push origin",
    "git-commit-helper",
    "legit commit",
    "gh pr view 3",
    "gh pr list",
    "gh pr list --state open",
    "gh pr view 3 --json title",
    "gh pr checks 12",
    "gh issue create",
    "npm run commit-lint",
    # Claude initializes a plain folder project (D041).
    "git init",
    "git init -b main",
    "cd notes && git init && git add -A",
    "",
    # Normal reads with quoted arguments and options.
    'git -C "my dir" status',
    "git -C 'dir with space' diff --stat",
    'git log --format="%h %s" -5',
    "git add -A && git status",
    "git -c core.pager=cat log --oneline",
    "git -c alias.st=status st",
    "git -c alias.x=x x",
    "git -c alias.x x status",
    "git --namespace=alias.x=commit x",
    "git config user.name",
    "git config --get remote.origin.url",
    "git config alias.lg 'log --oneline'",
    "git remote -v",
    "git fetch origin",
    "git branch -a",
    "git rev-parse HEAD",
    "git show --stat HEAD",
    "git blame -L 1,5 README.md",
    "git worktree list",
    "git subtree split --prefix=x",
    'git diff HEAD~1 -- "src/push helper.ts"',
    "git diff $(git merge-base HEAD main)",
    'for f in *.py; do git diff "$f"; done',
    "cd ~/git && git status",
    "git -C x",
    "git --version",
    "gh",
    "gh pr",
    "gh pr view 3; echo create",
    "npm test && git status",
    'ls "my dir"',
    "cat <<EOF\nhello\nEOF",
    "echo committed",
    # Commits are allowed for pixies too (D123).
    "git co\\mmit -m x",
    "git commit -m 'x'",
    "cd sub && git commit --allow-empty -m b",
    "ls | xargs git commit -m x",
    "sh -c 'git commit --allow-empty -m c'",
    "git -c user.name=x commit --allow-empty -m d",
    "git --no-pager -c a=b -C dir commit",
    "git --git-dir /x/.git --work-tree /x commit -am y",
    "/usr/bin/git commit -m x",
    "env GIT_AUTHOR_NAME=x git commit",
    "git 'commit' -m quoted",
    "echo $(git commit -m inline)",
    "git\tcommit",
    "git commit-tree HEAD^{tree}",
    'git -C "my dir" commit -m x',
    'git -c user.name="A B" commit -m x',
    '"git" commit -m x',
    'git commit -m "unbalanced',
    'FOO="a b" git commit -m x',
    "nice -n 5 git commit -m x",
    "git COMMIT -m x",
    "/usr/libexec/git-core/git-commit -m x",
    "f() { git commit -m x; }; f",
    "bash -c 'cd \"a b\" && git commit -m x'",
    "git $(echo commit) -m x",
    "git -c alias.ci=commit ci -m x",
    "git -c alias.CI=commit ci -m x",
    "git -c alias.x='!sh -c \"git commit\"' x",
    "git -c alias.a=b -c alias.b=commit a",
    "git config alias.ci commit",
    "echo 'git commit'",
    "echo git commit",
    # Lines plainly harmless that only mention a blocked command (B132).
    'grep -rn "git push" src',
    "grep 'gh pr merge' README.md",
    'rg "gh pr create" .',
    'rg -n "git push" --type py',
    'echo "git push"',
    "echo 'git push'",
    "echo git push",
    "echo gh pr merge 1\n",
    "docker push $IMAGE",
    'docker push "$IMAGE"',
    "docker push ${IMAGE}",
    "docker push ghcr.io/o/r:$TAG",
    "git commit -m \"$(cat <<'EOF'\nfix: git push (again)\n\nit's fine\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nfix(daemon): stop git push\nEOF\n)\"",
    "git commit -a -m \"$(cat <<'E'\ngh pr merge is off\nE\n)\"",
    'git commit -am "$(cat <<\'EOF\'\nrun `git push` and $HOME; echo "x"\nEOF\n)"',
    "git commit --amend --no-verify -m \"$(cat <<'EOF'\ngit push\nEOF\n)\"",
    # The shell wrapper Codex runs commands in.
    "bash -lc 'grep \"git push\" src'",
    "/bin/zsh -lc \"grep 'gh pr create' .\"",
    "/bin/zsh -lc 'docker push $IMAGE'",
    # A `$` on a line that names neither push nor a pull request write.
    'gh pr list --search "$Q"',
    # gh api reads.
    "gh api repos/o/r/pulls",
    "gh api repos/o/r/pulls/3",
    "gh api repos/o/r/pulls/3/merge",
    "gh api repos/{owner}/{repo}/pulls --paginate",
    "gh api repos/$O/$R/pulls",
    "gh api repos/o/r/commits/$(git rev-parse HEAD)",
    "gh api repos/o/r/pulls --jq '.[] | .title'",
    "gh api repos/o/r/pulls | jq .",
    "gh api -i repos/o/r",
    "gh api -H 'Accept: application/json' repos/o/r",
    "gh api --jq -f repos/o/r",
    "gh api repos/o/r/pulls -X GET -f state=open",
    "gh api --method GET search/issues -f q=x",
    "gh api -XGET search/issues -F per_page=5",
    "gh api graphql -f query='query { viewer { login } }'",
    "gh api graphql -F owner=o -f query='query($owner: String!) { user(login: $owner) { id } }'",
    "gh api graphql -f query='{ viewer { login } }' --jq .data",
    # Other gh reads.
    "gh auth status",
    "gh auth status --hostname github.com",
    "gh auth status -a",
    "git config --get credential.helper",
    "git config alias.h 'config --get credential.helper'",
    "GIT_PAGER=cat git log -1",
    "env GIT_DIR=.git git status",
    "export GIT_CONFIG_COUNT=1",
    "gh repo view o/r",
    "gh alias list",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_pushes_and_pull_request_writes(command: str) -> None:
    assert is_git_write(command) is True


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_read_only_and_unrelated_commands(command: str) -> None:
    assert is_git_write(command) is False


def test_permission_rules_cover_the_same_commands() -> None:
    assert GIT_WRITE_RULES == (
        "Bash(git push:*)",
        "Bash(gh pr create:*)",
        "Bash(gh pr merge:*)",
    )


TOOL_WRITES: list[tuple[str, dict[str, object]]] = [
    # Any tool whose input carries a command line or argv.
    ("mcp__plugin_serena_serena__execute_shell_command", {"command": "git push"}),
    ("Monitor", {"command": "git -C 'a b' push", "description": "watch"}),
    ("mcp__shell__run", {"cmd": "git push origin x"}),
    ("mcp__shell__run", {"script": "cd x\ngit push"}),
    ("mcp__shell__run", {"shellCommand": "gh pr create"}),
    ("mcp__shell__run", {"command_line": "git push"}),
    ("mcp__proc__spawn", {"args": ["git", "push"]}),
    ("mcp__proc__spawn", {"argv": ["sh", "-c", "git push origin x"]}),
    ("mcp__proc__spawn", {"command": ["git", "push", 3]}),
    # MCP tools that open or merge pull requests or write to a remote by themselves.
    ("mcp__github__create_pull_request", {"title": "x"}),
    ("mcp__github__merge_pull_request", {"pull_number": 1}),
    ("mcp__github__push_files", {"files": []}),
    ("mcp__github__create_or_update_file", {"path": "a"}),
    ("mcp__github__create_commit", {"message": "x"}),
    ("mcp__git__git_push", {}),
    ("mcp__plugin_engineering_github__createPullRequest", {}),
]

TOOL_PASSES: list[tuple[str, dict[str, object]]] = [
    ("Bash", {"command": "git status"}),
    ("Bash", {"command": 3}),
    ("Bash", {}),
    ("Edit", {"file_path": "a.sh", "old_string": "x", "new_string": "git push"}),
    ("Write", {"file_path": "ship.sh", "content": "git push\n"}),
    ("Skill", {"skill": "x", "args": "git push"}),
    ("mcp__plugin_serena_serena__execute_shell_command", {"command": "git status"}),
    ("mcp__github__get_pull_request", {"pull_number": 1}),
    ("mcp__github__list_commits", {}),
    ("mcp__github__create_issue", {"title": "push the release"}),
    ("mcp__git__git_status", {}),
    ("mcp__git__git_commit", {"message": "x"}),
    ("Bash", {"command": "git commit -m x"}),
    ("git_push_helper", {}),
]


@pytest.mark.parametrize(("tool_name", "tool_input"), TOOL_WRITES)
def test_tools_that_run_or_are_git_writes_are_caught(
    tool_name: str, tool_input: dict[str, object]
) -> None:
    assert tool_writes(tool_name, tool_input) is True


@pytest.mark.parametrize(("tool_name", "tool_input"), TOOL_PASSES)
def test_other_tools_and_inputs_pass(tool_name: str, tool_input: dict[str, object]) -> None:
    assert tool_writes(tool_name, tool_input) is False


def pre_tool_use(tool_input: dict[str, object], tool_name: str = "Bash") -> PreToolUseHookInput:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "transcript_path": "/t",
        "cwd": "/c",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "tu1",
        "agent_id": "a",
        "agent_type": "main",
    }


CONTEXT: HookContext = {"signal": None}
DENIED = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": DENY_REASON,
    }
}


async def test_hook_denies_blocked_bash_commands_with_a_reason() -> None:
    output = await block_git_writes(pre_tool_use({"command": "git push"}), "tu1", CONTEXT)

    assert output == DENIED


async def test_hook_denies_other_tools_that_would_write() -> None:
    serena = pre_tool_use(
        {"command": 'git -C "a b" push'}, "mcp__plugin_serena_serena__execute_shell_command"
    )
    github = pre_tool_use({"title": "x"}, "mcp__github__create_pull_request")

    assert await block_git_writes(serena, "tu1", CONTEXT) == DENIED
    assert await block_git_writes(github, "tu1", CONTEXT) == DENIED


@pytest.mark.parametrize("tool_input", [{"command": "git status"}, {"command": 3}, {}])
async def test_hook_passes_other_commands_through(tool_input: dict[str, object]) -> None:
    assert await block_git_writes(pre_tool_use(tool_input), "tu1", CONTEXT) == {}


async def test_a_subagent_in_a_normal_chat_cannot_push_but_the_chat_can() -> None:
    """B127, and a pixie's ordinary subagent is `general-purpose`, which once passed."""
    pixie = pre_tool_use({"command": "git push origin main"})
    pixie["agent_type"] = "closer"
    ordinary = pre_tool_use({"command": "git push origin main"})
    ordinary["agent_type"] = "general-purpose"
    chat: dict[str, object] = dict(pre_tool_use({"command": "git push origin main"}))
    del chat["agent_id"], chat["agent_type"]
    # `claude --agent x`: the main agent has a type but no id.
    named_chat = {**chat, "agent_type": "x"}
    merge = pre_tool_use({"command": "git merge --no-ff topic"})

    assert await block_subagent_git_writes(pixie, "tu1", CONTEXT) == DENIED
    assert await block_subagent_git_writes(ordinary, "tu1", CONTEXT) == DENIED
    assert await block_subagent_git_writes(cast(HookInput, chat), "tu1", CONTEXT) == {}
    assert await block_subagent_git_writes(cast(HookInput, named_chat), "tu1", CONTEXT) == {}
    assert await block_subagent_git_writes(merge, "tu1", CONTEXT) == {}


async def test_hook_ignores_other_hook_events() -> None:
    prompt: UserPromptSubmitHookInput = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s",
        "transcript_path": "/t",
        "cwd": "/c",
        "prompt": "git push",
    }

    assert await block_git_writes(prompt, None, CONTEXT) == {}


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "sh -c 'git push origin main'",
        "gh pr create",
        "gh pr merge 1",
        "git worktree remove ../other",
        "git worktree remove --force ../other",
        "git -C .. worktree remove other",
        "git config alias.w 'worktree remove'",
        "git -c alias.w='worktree remove' w ../other",
        "git-worktree remove ../other",
        "sh -c 'git worktree remove ../other'",
        'git worktree "$ACTION" ../other',
        "W=worktree; git $W remove ../other",
        # Inside another command, and hidden by text (report item 6).
        "git rebase -x 'git worktree remove ../x' HEAD~1",
        "git submodule foreach 'git worktree remove ../x'",
        "git bisect run sh -c 'git worktree remove ../x'",
        "trap 'git worktree remove ../x' EXIT",
        'echo "<<E"\ngit worktree remove ../x\nE',
        "# <<E\ngit worktree remove ../x\nE",
        "cat <<E |\ngit worktree remove ../x\nE\nsh",
        "# Let's tidy\ngit worktree remove ../x\n# Don't forget",
    ],
)
def test_autopilot_blocks_pushes_pull_requests_and_removing_worktrees(command: str) -> None:
    assert is_git_write(command, worktrees=True)


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git add .",
        "git commit -m x",
        "git -C /tmp/a merge main",
        "git rebase main",
        "git cherry-pick abc",
        "git revert HEAD",
        "git pull",
        "git-commit -m x",
        "git worktree list",
        "git worktree add ../other",
        'git worktree add "$DIR"',
    ],
)
def test_autopilot_may_do_the_rest_of_git(command: str) -> None:
    assert not is_git_write(command, worktrees=True)


@pytest.mark.parametrize(
    ("command", "flagged"),
    [
        ("git worktree remove ../other", True),
        ("sh -c 'git worktree remove ../other'", True),
        ("git push && git worktree remove ../other", True),
        ("git push", False),
        ("gh pr merge 1", False),
        ("git -c alias.ship=push ship", False),
        ("git config alias.p push", False),
    ],
)
def test_with_pushes_allowed_only_removing_a_worktree_is_flagged(
    command: str, flagged: bool
) -> None:
    assert is_git_write(command, pushes=False, worktrees=True) is flagged


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git worktree remove ../other",
        "git --config-env=alias.p=X p",
        "git -c 'alias.x=log \"a' x",
        'git commit -m "unbalanced git push',
    ],
)
def test_a_run_that_watches_nothing_flags_nothing(command: str) -> None:
    assert not is_git_write(command, pushes=False)


def test_a_tool_that_pushes_passes_with_pushes_allowed() -> None:
    assert not tool_writes("mcp__github__create_pull_request", {"title": "x"}, pushes=False)


def _git(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A clone with a commit that is not on its bare remote yet, and that remote."""
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "Nest")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "nest@example.com")
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    assert _git(tmp_path, "init", "--bare", "-b", "main", str(remote)).returncode == 0
    assert _git(tmp_path, "init", "-b", "main", str(work)).returncode == 0
    (work / "a").write_text("a", encoding="utf-8")
    assert _git(work, "add", "a").returncode == 0
    assert _git(work, "commit", "-m", "one").returncode == 0
    assert _git(work, "remote", "add", "origin", remote.as_uri()).returncode == 0
    assert _git(work, "push", "origin", "main").returncode == 0
    assert _git(work, "commit", "--allow-empty", "-m", "two").returncode == 0
    return work, remote


def _blocked_env() -> dict[str, str]:
    return {**os.environ, **NO_PUSH_ENV}


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "main").stdout


def test_the_git_level_block_stops_a_real_push_and_leaves_fetch_and_pull(
    clone: tuple[Path, Path],
) -> None:
    work, remote = clone
    before = _head(remote)

    pushed = _git(work, "push", "origin", "main", env=_blocked_env())

    assert pushed.returncode != 0
    assert "nest-pushing-is-off" in pushed.stderr
    assert _head(remote) == before
    assert _git(work, "fetch", "origin", env=_blocked_env()).returncode == 0
    assert _git(work, "pull", "--no-edit", "origin", "main", env=_blocked_env()).returncode == 0


@pytest.mark.parametrize(
    "url", ["https://example.invalid/r.git", "git@example.invalid:r.git", "ssh://example.invalid/r"]
)
def test_the_git_level_block_never_reaches_a_network_remote(
    clone: tuple[Path, Path], url: str
) -> None:
    work, _ = clone

    pushed = _git(work, "push", url, "main", env=_blocked_env())

    assert pushed.returncode != 0
    assert "nest-pushing-is-off" in pushed.stderr


def test_the_git_level_block_adds_no_remote_to_a_repo_without_origin(
    clone: tuple[Path, Path],
) -> None:
    work, _ = clone
    assert _git(work, "remote", "rename", "origin", "upstream").returncode == 0

    assert _git(work, "remote", env=_blocked_env()).stdout.split() == ["upstream"]
    assert _git(work, "fetch", "--all", env=_blocked_env()).returncode == 0
    assert _git(work, "remote", "update", env=_blocked_env()).returncode == 0


def test_without_the_block_the_same_push_works(clone: tuple[Path, Path]) -> None:
    work, remote = clone

    assert _git(work, "push", "origin", "main").returncode == 0
    assert _head(remote) == _head(work)


def test_a_pixie_may_still_commit() -> None:
    assert not is_git_write("git commit -m x")
    assert not is_git_write("git merge main")
