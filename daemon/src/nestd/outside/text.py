"""How the `nest` command and `nest mcp` say what Nest answered (B151)."""

from nestd.outside.models import ACCESS_LABELS, Chat, ChatDetails, PixieEntry, Project, Status

SHORT_ID = 8


def status_text(status: Status) -> str:
    return (
        f"Nest {status.version} is running: {_chats(status.running)} running,"
        f" {status.waiting} waiting on the user. This client has"
        f" {ACCESS_LABELS[status.access]} access."
    )


def project_lines(projects: list[Project]) -> str:
    return "\n".join(f"{p.name}  {p.path}" for p in projects) or "No projects."


def chat_line(chat: Chat) -> str:
    return f"{chat.id[:SHORT_ID]}  {chat.status:<18}  {chat.project:<14}  {chat.title}"


def chat_lines(chats: list[Chat]) -> str:
    return "\n".join(chat_line(c) for c in chats) or "No chats."


def pixie_lines(pixies: list[PixieEntry]) -> str:
    lines = [f"@{p.handle}  {p.name}{'  (team)' if p.kind == 'team' else ''}" for p in pixies]
    return "\n".join(lines) or "No pixies."


def chat_details(chat: ChatDetails) -> str:
    work = f"worktree, branch {chat.branch}" if chat.worktree else "in the project's folder"
    lines = [
        f'Chat {chat.id} "{chat.title}"',
        f"Project: {chat.project}, {work}",
        f"Status: {chat.status}",
        f"Engine: {chat.engine}, {chat.model or 'default model'}, {chat.permission_mode} mode",
        f"Started by: {chat.started_by}",
    ]
    if chat.pr_url:
        lines.append(f"Pull request: {chat.pr_url}")
    if chat.last_error:
        lines.append(f"Error: {chat.last_error}")
    if chat.state == "waiting":
        lines.append(
            f"It waits on the user in Nest; `nest open {chat.id[:SHORT_ID]}` opens it there."
        )
    if chat.last_answer:
        lines += ["", "Last answer:", chat.last_answer]
    return "\n".join(lines)


def _chats(count: int) -> str:
    return "1 chat" if count == 1 else f"{count} chats"
