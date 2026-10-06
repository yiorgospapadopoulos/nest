"""A sanitized transcript shaped like a real Claude Code session (2.1.285): a task list,
an Explore subagent started with the Agent tool, and a file write.
"""

from pydantic import JsonValue

ROOT = "/work/demo"
AGENT_ID = "toolu_agent"


def tool_use(call_id: str, name: str, tool_input: dict[str, JsonValue]) -> JsonValue:
    return {"type": "tool_use", "id": call_id, "name": name, "input": tool_input}


def tool_result(call_id: str, content: str, is_error: bool = False) -> JsonValue:
    return {"type": "tool_result", "tool_use_id": call_id, "content": content, "is_error": is_error}


def text(value: str) -> JsonValue:
    return {"type": "text", "text": value}


def message(*blocks: JsonValue, parent: str | None = None) -> dict[str, JsonValue]:
    return {"blocks": list(blocks), "parent_tool_use_id": parent}


def start_agent_message(
    call: str, parent: str | None = None, **fields: JsonValue
) -> dict[str, JsonValue]:
    tool_input: dict[str, JsonValue] = {"description": "Look around", "subagent_type": "Explore"}
    tool_input.update(fields)
    return message(tool_use(call, "Agent", tool_input), parent=parent)


def create_task(n: int, subject: str, active: str) -> list[dict[str, JsonValue]]:
    call = f"toolu_create{n}"
    return [
        message(
            tool_use(
                call,
                "TaskCreate",
                {"subject": subject, "description": f"About {subject}", "activeForm": active},
            )
        ),
        message(tool_result(call, f"Task #{n} created successfully: {subject}")),
    ]


def update_task(call: str, task_id: str, status: str) -> list[dict[str, JsonValue]]:
    return [
        message(tool_use(call, "TaskUpdate", {"taskId": task_id, "status": status})),
        message(tool_result(call, f"Updated task #{task_id} status")),
    ]


def transcript() -> list[tuple[str, dict[str, JsonValue]]]:
    """(event type, payload) pairs in the order the daemon persists them."""
    events: list[tuple[str, dict[str, JsonValue]]] = [
        ("session.created", {"session": {"cwd": None, "title": "Demo"}}),
        ("session.state", {"state": "starting", "error": None}),
        ("session.workspace", {"path": ROOT, "branch": "agent/demo"}),
        ("session.state", {"state": "running", "error": None}),
        ("session.message", message({"type": "thinking", "text": ""})),
        ("session.message", message(text("I'll create the tasks."))),
    ]
    messages = [
        *create_task(1, "Read CLAUDE.md", "Reading CLAUDE.md"),
        *create_task(2, "Write summary.txt", "Writing summary.txt"),
        *update_task("toolu_u1", "1", "in_progress"),
        message(
            tool_use(
                AGENT_ID,
                "Agent",
                {
                    "description": "Read CLAUDE.md file",
                    "subagent_type": "Explore",
                    "prompt": f"Read {ROOT}/CLAUDE.md",
                    "run_in_background": False,
                },
            )
        ),
        message(text(f"Read {ROOT}/CLAUDE.md"), parent=AGENT_ID),
        message(
            tool_use("toolu_read", "Read", {"file_path": f"{ROOT}/CLAUDE.md"}), parent=AGENT_ID
        ),
        message(tool_result("toolu_read", "1\tDemo repo.\n2\t"), parent=AGENT_ID),
        message(tool_result(AGENT_ID, "[Subagent hand-back] The file says: Demo repo.")),
        *update_task("toolu_u2", "1", "completed"),
        message(
            tool_use("toolu_write", "Write", {"file_path": f"{ROOT}/summary.txt", "content": "x"})
        ),
        message(tool_result("toolu_write", f"File created successfully at: {ROOT}/summary.txt")),
        *update_task("toolu_u3", "2", "completed"),
        message(text("Done. Both tasks completed.")),
    ]
    events.extend(("session.message", m) for m in messages)
    events.append(("session.state", {"state": "idle", "error": None}))
    return events
