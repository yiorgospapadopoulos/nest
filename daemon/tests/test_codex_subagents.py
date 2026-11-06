"""Codex's own subagents as Claude Code's (B112): pixies a Codex run calls are agent roles
of its thread, and their threads show as Claude subagents do."""

import asyncio
import tomllib
from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue

from nestd.providers.base import (
    AgentTask,
    CallRules,
    PlanStep,
    QuestionAnswer,
    QuestionRequest,
    Subagent,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserInput,
)
from nestd.providers.codex_agents import LAUNCHED, MEMBER_REFUSED
from nestd.providers.codex_roles import CodexRoles
from nestd.providers.codex_rpc import JsonObject
from tests.async_support import until
from tests.codex_support import FakeAppServer, note
from tests.recording_sink import RecordingSink
from tests.test_codex_provider import Handler, opened, provider, spec

MAIN = "thread-1"
AGENT = "agent-1"

SCOUT = Subagent(
    description="Scout: finds things",
    prompt="You are Scout (@scout), a pixie.",
    permission_mode="bypassPermissions",
    model="gpt-5.5",
    effort="low",
)
READER = Subagent(
    description="Reader: reads",
    prompt="You are Reader.",
    permission_mode="default",
    disallowed_tools=("Edit", "Write", "MultiEdit", "NotebookEdit"),
)
LEAD = Subagent(description="Lead", prompt="You lead.", permission_mode="default")
BUGS = Subagent(description="Bugs", prompt="You find bugs.", permission_mode="default")
TEAM = CallRules(
    pixies=frozenset({"scout", "lead", "bugs"}),
    main=frozenset({"scout", "lead"}),
    leaders={"lead": frozenset({"bugs"})},
)


def collab(
    phase: str, tool: str, item_id: str, receivers: list[str], **fields: JsonValue
) -> JsonObject:
    body: JsonObject = {
        "type": "collabAgentToolCall",
        "id": item_id,
        "tool": tool,
        "senderThreadId": fields.pop("sender", MAIN),
        "receiverThreadIds": list[JsonValue](receivers),
        "status": "inProgress" if phase == "started" else "completed",
        "agentsStates": {},
        **fields,
    }
    return note(f"item/{phase}", threadId=body["senderThreadId"], turnId="turn-1", item=body)


def spawned(thread_id: str, role: str | None, parent: str = MAIN) -> JsonObject:
    source: JsonObject = {
        "subAgent": {"thread_spawn": {"parent_thread_id": parent, "depth": 1, "agent_role": role}}
    }
    return note(
        "thread/started",
        thread={
            "id": thread_id,
            "parentThreadId": parent,
            "agentRole": role,
            "source": source,
            "preview": "",
        },
    )


def on(thread_id: str, method: str, **params: JsonValue) -> JsonObject:
    return note(method, threadId=thread_id, **params)


def turn(thread_id: str, phase: str, status: str = "completed", turn_id: str = "t-a") -> JsonObject:
    body: JsonObject = {"id": turn_id}
    if phase == "completed":
        body |= {"status": status, "error": None, "durationMs": 5}
    return on(thread_id, f"turn/{phase}", turn=body)


def said(thread_id: str, item_id: str, words: str) -> JsonObject:
    return on(
        thread_id,
        "item/completed",
        turnId="t-a",
        item={"type": "agentMessage", "id": item_id, "text": words},
    )


def push(server: FakeAppServer, *messages: JsonObject) -> None:
    for message in messages:
        server.notify(str(message["method"]), cast("JsonObject", message["params"]))


def spawn(server: FakeAppServer, thread_id: str = AGENT, role: str | None = "scout") -> None:
    push(
        server,
        collab("started", "spawnAgent", "call-1", [], prompt="Find the bug"),
        spawned(thread_id, role),
        collab("completed", "spawnAgent", "call-1", [thread_id], prompt="Find the bug"),
    )


def _role(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text())


def calls(sink: RecordingSink, kind: str) -> list[object]:
    return [value for name, value in sink.calls if name == kind]


def agent_call(role: str, prompt: str = "Find the bug", thread_id: str = AGENT) -> ToolUseBlock:
    return ToolUseBlock(
        id=thread_id,
        name="Agent",
        input={
            "subagent_type": role,
            "description": role,
            "prompt": prompt,
            "run_in_background": False,
        },
    )


async def test_a_pixie_on_codex_is_a_role_of_the_thread_with_its_call_prompt(
    tmp_path: Path,
) -> None:
    server, run, _, _ = await opened(
        tmp_path, subagents={"scout": SCOUT}, call_rules=TEAM, permission_mode="default"
    )

    [start] = server.requests("thread/start")
    config = cast("JsonObject", start["config"])
    assert config["features.multi_agent"] is True
    assert config["agents.scout.description"] == "Scout: finds things"
    role_file = Path(str(config["agents.scout.config_file"]))
    role = _role(role_file)
    assert role["developer_instructions"] == "You are Scout (@scout), a pixie."
    assert (role["model"], role["model_reasoning_effort"]) == ("gpt-5.5", "low")
    # Its commands come to Nest, which keeps the pixie's own bypass and declines pushes.
    assert (role["approval_policy"], role["sandbox_mode"]) == ("untrusted", "danger-full-access")
    assert "spawn_agent" in str(start["developerInstructions"])
    # Never in the user's config: only in the run's own folder, gone with the run.
    await run.close()
    assert not await asyncio.to_thread(role_file.exists)


async def test_a_native_call_shows_as_a_claude_subagent_with_its_activity_and_report(
    tmp_path: Path,
) -> None:
    server, run, sink, _ = await opened(tmp_path, subagents={"scout": SCOUT}, call_rules=TEAM)
    server.script(
        collab("started", "spawnAgent", "call-1", [], prompt="Find the bug"),
        spawned(AGENT, "scout"),
        collab("completed", "spawnAgent", "call-1", [AGENT], prompt="Find the bug"),
        turn(AGENT, "started"),
        on(AGENT, "item/agentMessage/delta", delta="Look"),
        on(
            AGENT,
            "item/started",
            turnId="t-a",
            item={"type": "commandExecution", "id": "cmd-1", "command": "rg bug"},
        ),
        on(
            AGENT,
            "item/completed",
            turnId="t-a",
            item={
                "type": "commandExecution",
                "id": "cmd-1",
                "command": "rg bug",
                "status": "completed",
                "exitCode": 0,
                "aggregatedOutput": "a.py:3",
            },
        ),
        on(
            AGENT,
            "turn/plan/updated",
            turnId="t-a",
            plan=[{"step": "Search", "status": "inProgress"}],
        ),
        said(AGENT, "m-1", "It is in a.py"),
        turn(AGENT, "completed"),
        note("turn/completed", threadId=MAIN, turn={"id": "turn-1", "status": "completed"}),
    )

    await run.send(UserInput("@scout find the bug"))
    await until(lambda: bool(calls(sink, "result")))

    messages = calls(sink, "message")
    assert messages[0] == ([agent_call("scout")], None)
    assert messages[1] == (
        [ToolUseBlock(id="cmd-1", name="Bash", input={"command": "rg bug"})],
        AGENT,
    )
    assert messages[2] == ([ToolResultBlock(tool_use_id="cmd-1", content="a.py:3")], AGENT)
    assert messages[3] == ([TextBlock(text="It is in a.py")], AGENT)
    # A foreground call: its result is the agent's report, before its caller's turn ends.
    assert messages[4] == ([ToolResultBlock(tool_use_id=AGENT, content="It is in a.py")], None)
    assert calls(sink, "subagent_delta") == [("Look", AGENT)]
    assert calls(sink, "plan") == [([PlanStep(text="Search", status="in_progress")], AGENT)]
    assert calls(sink, "task") == [
        AgentTask(
            task_id=AGENT,
            phase="started",
            tool_use_id=AGENT,
            task_type="local_agent",
            description="scout",
        ),
        AgentTask(
            task_id=AGENT,
            phase="finished",
            tool_use_id=AGENT,
            status="completed",
            summary="It is in a.py",
        ),
    ]
    assert calls(sink, "background_tasks") == [1, 0]
    await run.close()


async def test_a_spawned_thread_codex_cannot_read_at_first_still_gets_its_pixie(
    tmp_path: Path,
) -> None:
    # Live check 2026-10-27: Codex sent no thread/started and the first thread/read
    # failed, so the pixie's call showed as "default".
    server, run, sink, _ = await opened(tmp_path, subagents={"scout": SCOUT}, call_rules=TEAM)
    server.errors["thread/read"] = (-32600, "thread not loaded")
    server.answers["thread/read"] = {
        "thread": {"id": AGENT, "parentThreadId": MAIN, "agentRole": "scout", "preview": ""}
    }
    push(
        server,
        collab("started", "spawnAgent", "call-1", [], prompt="Find the bug"),
        collab("completed", "spawnAgent", "call-1", [AGENT], prompt="Find the bug"),
    )
    await until(lambda: bool(server.requests("thread/read")))
    del server.errors["thread/read"]

    await until(lambda: bool(calls(sink, "message")))
    assert calls(sink, "message")[0] == ([agent_call("scout")], None)
    await run.close()


async def test_an_agent_its_caller_did_not_wait_for_goes_on_in_the_background(
    tmp_path: Path,
) -> None:
    server, run, sink, _ = await opened(tmp_path, subagents={"scout": SCOUT}, call_rules=TEAM)
    spawn(server)
    push(server, turn(AGENT, "started"))
    await until(lambda: calls(sink, "background_tasks") == [1])

    push(
        server, note("turn/completed", threadId=MAIN, turn={"id": "turn-1", "status": "completed"})
    )
    await until(lambda: bool(calls(sink, "result")))
    background = sink.calls.index(("task", AgentTask(task_id=AGENT, phase="backgrounded")))
    launched = (
        "message",
        ([ToolResultBlock(tool_use_id=AGENT, content=LAUNCHED.format(agent_id=AGENT))], None),
    )
    assert sink.calls.index(launched) == background + 1
    assert background < sink.calls.index(("result", calls(sink, "result")[0]))

    push(server, said(AGENT, "m-1", "Done: a.py"), turn(AGENT, "completed"))
    await until(lambda: len(calls(sink, "task")) == 3)
    # The report comes with the task's end, as a Claude background agent's does.
    assert calls(sink, "task")[-1] == AgentTask(
        task_id=AGENT, phase="finished", tool_use_id=AGENT, status="completed", summary="Done: a.py"
    )
    assert calls(sink, "background_tasks") == [1, 0]
    await run.close()


async def test_a_message_to_an_earlier_agent_continues_it_as_a_send_message(
    tmp_path: Path,
) -> None:
    server, run, sink, _ = await opened(tmp_path, subagents={"scout": SCOUT}, call_rules=TEAM)
    spawn(server)
    push(server, turn(AGENT, "started"), said(AGENT, "m-1", "First"), turn(AGENT, "completed"))
    await until(lambda: len(calls(sink, "task")) == 2)

    push(
        server,
        collab("started", "sendInput", "call-2", [AGENT], prompt="Now the tests"),
        collab("completed", "sendInput", "call-2", [AGENT], prompt="Now the tests"),
        turn(AGENT, "started", turn_id="t-b"),
        said(AGENT, "m-2", "Tests fixed"),
        turn(AGENT, "completed", turn_id="t-b"),
    )
    await until(lambda: len(calls(sink, "task")) == 3)

    message = ToolUseBlock(
        id="call-2", name="SendMessage", input={"to": AGENT, "message": "Now the tests"}
    )
    assert ([message], None) in calls(sink, "message")
    assert ([TextBlock(text="Tests fixed")], AGENT) in calls(sink, "message")
    # Its first call has its result already; the continued one ends with its task.
    results = [
        block
        for blocks, _ in cast("list[tuple[list[object], str | None]]", calls(sink, "message"))
        for block in blocks
        if isinstance(block, ToolResultBlock) and block.tool_use_id == AGENT
    ]
    assert len(results) == 1
    assert calls(sink, "task")[-1] == AgentTask(
        task_id=AGENT,
        phase="finished",
        tool_use_id=AGENT,
        status="completed",
        summary="Tests fixed",
    )
    await run.close()


async def test_a_call_the_rules_forbid_is_refused_and_its_agent_stopped(tmp_path: Path) -> None:
    server, run, sink, handler = await opened(
        tmp_path, subagents={"lead": LEAD, "bugs": BUGS}, call_rules=TEAM
    )
    spawn(server, role="bugs")
    push(server, turn(AGENT, "started"))
    await until(lambda: bool(server.requests("turn/interrupt")))

    assert calls(sink, "message")[:2] == [
        ([agent_call("bugs")], None),
        (
            [
                ToolResultBlock(
                    tool_use_id=AGENT, content=MEMBER_REFUSED.format(slug="bugs"), is_error=True
                )
            ],
            None,
        ),
    ]
    assert server.requests("turn/interrupt") == [{"threadId": AGENT, "turnId": "t-a"}]
    answer = await server.request(
        "item/commandExecution/requestApproval",
        {"threadId": AGENT, "itemId": "c1", "command": "ls"},
    )
    assert answer["result"] == {"decision": "decline"}
    assert handler.requests == []
    assert calls(sink, "task") == []
    await run.close()


async def test_a_leader_calls_its_members_under_its_own_call(tmp_path: Path) -> None:
    server, run, sink, _ = await opened(
        tmp_path, subagents={"lead": LEAD, "bugs": BUGS}, call_rules=TEAM
    )
    spawn(server, role="lead")
    push(
        server,
        collab("started", "spawnAgent", "call-9", [], prompt="Check", sender=AGENT),
        spawned("agent-2", "bugs", parent=AGENT),
        collab("completed", "spawnAgent", "call-9", ["agent-2"], prompt="Check", sender=AGENT),
    )
    await until(lambda: len(calls(sink, "task")) == 2)

    assert calls(sink, "message")[1] == ([agent_call("bugs", "Check", "agent-2")], AGENT)
    await run.close()


async def test_a_subagents_approvals_follow_its_own_mode(tmp_path: Path) -> None:
    server, run, _, handler = await opened(
        tmp_path, subagents={"scout": SCOUT, "reader": READER}, call_rules=None
    )
    spawn(server)
    spawn(server, thread_id="agent-2", role="reader")
    await until(lambda: run.stream.agents.thread("agent-2") is not None)

    command = await server.request(
        "item/commandExecution/requestApproval",
        {"threadId": AGENT, "itemId": "c1", "command": "npm test"},
    )
    edit = await server.request(
        "item/fileChange/requestApproval", {"threadId": "agent-2", "itemId": "f1"}
    )

    # Scout keeps its own bypass in a chat in default mode: nobody is asked.
    assert command["result"] == {"decision": "accept"}
    assert handler.requests == []
    # A read-only pixie edits nothing.
    assert edit["result"] == {"decision": "decline"}
    assert handler.requests == []
    await run.close()


async def test_a_pixie_in_a_normal_chat_cannot_push_but_may_commit_and_merge(
    tmp_path: Path,
) -> None:
    """B127: every engine's pixie stays out of pushes, in bypass too; the chat does not."""
    server, run, _, handler = await opened(tmp_path, subagents={"scout": SCOUT}, call_rules=None)
    spawn(server)
    await until(lambda: run.stream.agents.thread(AGENT) is not None)

    async def decision(thread_id: str, command: str) -> JsonValue:
        answer = await server.request(
            "item/commandExecution/requestApproval",
            {"threadId": thread_id, "itemId": "c1", "command": command},
        )
        return cast("JsonObject", answer["result"])["decision"]

    assert await decision(AGENT, "git push origin main") == "decline"
    assert await decision(AGENT, "git merge --no-ff topic") == "accept"
    assert await decision(AGENT, "git commit -m x") == "accept"
    assert run.permissions("").guarded is False
    assert handler.requests == []
    await run.close()


async def test_an_ordinary_subagent_in_a_normal_chat_cannot_push_either(tmp_path: Path) -> None:
    """D160: "subagents" in the setting is every subagent, as far as Codex asks Nest."""
    server, run, _, _ = await opened(tmp_path, subagents={"scout": SCOUT}, call_rules=None)
    spawn(server, role=None)
    await until(lambda: run.stream.agents.thread(AGENT) is not None)

    assert run.permissions(AGENT).guarded is True
    assert run.permissions("").guarded is False
    await run.close()


async def test_with_agents_allowed_to_push_a_pixie_may_push(tmp_path: Path) -> None:
    server, run, _, _ = await opened(
        tmp_path, subagents={"scout": SCOUT}, call_rules=None, guard_subagents=False
    )
    spawn(server)
    await until(lambda: run.stream.agents.thread(AGENT) is not None)

    assert run.permissions(AGENT).guarded is False
    await run.close()


def test_with_agents_allowed_to_push_a_pixies_role_follows_its_own_mode() -> None:
    roles = CodexRoles({"scout": SCOUT}, False, None, guard_pixies=False)
    roles.config("default")
    text = (roles.folder / "scout.toml").read_text(encoding="utf-8")
    roles.close()

    assert 'approval_policy = "never"' in text
    assert 'sandbox_mode = "danger-full-access"' in text


def test_a_bypass_pixies_role_still_asks_nest_about_its_commands() -> None:
    """Without this Codex never asks, and the decline above never gets a chance."""
    roles = CodexRoles({"scout": SCOUT}, False, None)
    roles.config("default")
    text = (roles.folder / "scout.toml").read_text(encoding="utf-8")
    roles.close()

    assert 'approval_policy = "untrusted"' in text


class Asking(Handler):
    def __init__(self) -> None:
        super().__init__()
        self.questions: list[QuestionRequest] = []

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        self.questions.append(request)
        return QuestionAnswer(None)


async def test_a_subagents_requests_name_its_thread(tmp_path: Path) -> None:
    """B114: what a subagent asks names its thread, its Agent call's id; the main
    thread's requests name none.
    """
    server = FakeAppServer()
    handler = Asking()
    run = await provider(tmp_path, server).open(
        spec(tmp_path, subagents={"lead": LEAD}), handler, RecordingSink()
    )
    spawn(server, role="lead")
    await until(lambda: run.stream.agents.thread(AGENT) is not None)
    question: JsonObject = {"id": "q1", "header": "H", "question": "Which?", "options": []}

    for thread in (AGENT, MAIN):
        await server.request(
            "item/commandExecution/requestApproval",
            {"threadId": thread, "itemId": "c1", "command": "npm test"},
        )
    await server.request(
        "item/tool/requestUserInput", {"threadId": AGENT, "itemId": "u1", "questions": [question]}
    )

    assert [r.agent_id for r in handler.requests] == [AGENT, None]
    assert [q.agent_id for q in handler.questions] == [AGENT]
    await run.close()


async def test_stopping_one_subagent_interrupts_its_thread_only(tmp_path: Path) -> None:
    server, run, sink, _ = await opened(tmp_path, subagents={"scout": SCOUT}, call_rules=TEAM)
    spawn(server)
    push(server, turn(AGENT, "started"))
    await until(lambda: calls(sink, "background_tasks") == [1])

    assert await run.stop_task(AGENT)
    assert not await run.stop_task("no-such-agent")
    assert server.requests("turn/interrupt") == [{"threadId": AGENT, "turnId": "t-a"}]

    push(server, turn(AGENT, "completed", status="interrupted"))
    await until(lambda: len(calls(sink, "task")) == 2)
    assert calls(sink, "task")[-1] == AgentTask(
        task_id=AGENT, phase="finished", tool_use_id=AGENT, status="stopped"
    )
    await run.close()


async def test_the_main_agents_plan_is_the_task_list(tmp_path: Path) -> None:
    server, run, sink, _ = await opened(tmp_path)
    push(
        server,
        on(
            MAIN,
            "turn/plan/updated",
            turnId="turn-1",
            plan=[
                {"step": "Read", "status": "completed"},
                {"step": "Fix", "status": "inProgress"},
                {"step": "Test", "status": "pending"},
            ],
        ),
    )
    await until(lambda: bool(calls(sink, "plan")))

    assert calls(sink, "plan") == [
        (
            [
                PlanStep(text="Read", status="completed"),
                PlanStep(text="Fix", status="in_progress"),
                PlanStep(text="Test", status="pending"),
            ],
            None,
        )
    ]
    await run.close()


async def test_a_skill_list_switches_the_other_skills_off_for_the_thread_and_its_roles(
    tmp_path: Path,
) -> None:
    server = FakeAppServer()
    server.answers["skills/list"] = {
        "data": [
            {
                "cwd": str(tmp_path),
                "errors": [],
                "skills": [
                    {
                        "name": "pdf",
                        "enabled": True,
                        "path": "/s/pdf",
                        "description": "",
                        "scope": "user",
                    },
                    {
                        "name": "imagegen",
                        "enabled": True,
                        "path": "/s/i",
                        "description": "",
                        "scope": "system",
                    },
                    {
                        "name": "old",
                        "enabled": False,
                        "path": "/s/o",
                        "description": "",
                        "scope": "user",
                    },
                ],
            }
        ]
    }
    scout = Subagent(
        description="Scout", prompt="You scout.", permission_mode="default", skills=("imagegen",)
    )

    run = await provider(tmp_path, server).open(
        spec(tmp_path, skills=("pdf",), subagents={"scout": scout}), Handler(), RecordingSink()
    )

    assert server.requests("skills/list") == [{"cwds": [str(tmp_path)]}]
    [start] = server.requests("thread/start")
    config = cast("JsonObject", start["config"])
    assert config["skills.config"] == [
        {"name": "imagegen", "enabled": False},
        {"name": "old", "enabled": False},
    ]
    role = _role(Path(str(config["agents.scout.config_file"])))
    assert role["skills"]["config"] == [
        {"name": "old", "enabled": False},
        {"name": "pdf", "enabled": False},
    ]
    await run.close()
