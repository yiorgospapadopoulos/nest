from pydantic import JsonValue

from nestd.errors import ConflictError, InvalidInputError, NotFoundError


class SessionNotFoundError(NotFoundError):
    pass


class SessionBusyError(ConflictError):
    pass


class SessionClosedError(ConflictError):
    pass


class NoTurnInProgressError(ConflictError):
    pass


class NoWorkspaceError(ConflictError):
    pass


class NotPausedError(ConflictError):
    """The chat is not paused at the usage limit, so there is nothing to resume (B78)."""

    code = "not_paused"

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class NoAgentRunError(ConflictError):
    """The session has no agent running, so nothing of it can be stopped (B59)."""


class TaskNotFoundError(NotFoundError):
    """The session's agent runs no task by that id (B59)."""


class AgentCallNotFoundError(NotFoundError):
    """The chat has no Agent call by that tool use id (B46)."""


class CannotRewindError(ConflictError):
    """The files or the conversation cannot be restored to before the message, or a chat
    forked from it (IMP-02, B59).
    """

    code = "cannot_rewind"

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class PixieChatError(ConflictError):
    """What a pixie's chat does not allow: it goes with its pixie (reset or delete the
    pixie instead), and its files cannot be restored (D072).
    """

    code = "pixie_chat"

    def __init__(
        self, detail: str = "this is a pixie's chat; reset or delete the pixie instead"
    ) -> None:
        super().__init__(detail)

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class MessageTakenError(ConflictError):
    """The agent already read the queued message, so it can no longer be removed (B59)."""

    code = "message_taken"

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class PixieInTeamError(InvalidInputError):
    """A message calls a pixie of a team on its own; it is called only with its team (B46)."""

    code = "pixie_in_team"

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


# What a chat on another engine cannot do, as the refusal says it (B91).
_FEATURE_WORDS: dict[str, str] = {
    "rewind": "be rewound",
    "fork": "be forked",
    "stop_task": "stop a single background task",
    "memory": "save a memory to CLAUDE.md",
    "pixie_skills": "be limited to chosen skills",
}
# What lacks the feature, when it is not a chat.
_FEATURE_SUBJECTS: dict[str, str] = {"pixie_skills": "pixie"}


class UnsupportedFeatureError(ConflictError):
    """The session's engine lacks the feature, so clients hide it (B91)."""

    code = "unsupported_feature"

    def __init__(self, provider: str, feature: str) -> None:
        self.provider = provider
        self.feature = feature
        words = _FEATURE_WORDS.get(feature, f"use {feature}")
        subject = _FEATURE_SUBJECTS.get(feature, "chat")
        super().__init__(f"A {provider.capitalize()} {subject} cannot {words}.")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "detail": str(self),
            "code": self.code,
            "provider": self.provider,
            "feature": self.feature,
        }
