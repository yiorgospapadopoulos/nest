"""Why a local model cannot be used now (B106)."""

from pydantic import JsonValue

from nestd.errors import ConflictError, NotFoundError

LOCAL_SERVER_DOWN = "local_server_down"


class LocalServerDownError(ConflictError):
    """The model's server does not answer; the message waits for the user to start it."""

    code = LOCAL_SERVER_DOWN

    def __init__(self, details: dict[str, JsonValue]) -> None:
        """`details` are the server's `app`, `address` and the `start` Nest offers."""
        self.details = details
        app = details.get("app") or "The model's server"
        super().__init__(f"{app} at {details.get('address')} is not running")

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code, **self.details}


class LocalModelNotLoadedError(Exception):
    """LM Studio did not load the model with the context an agent needs; its turn fails."""

    code = "local_model_not_loaded"

    def __init__(self, details: dict[str, JsonValue], reason: str) -> None:
        """`details` are the server's `app` and `address` and the `model`'s name."""
        self.details = details
        model, app = details.get("model"), details.get("app")
        super().__init__(
            f"{app} could not load {model} with enough context for an agent ({reason[:300]})."
            f" Load it in {app}, or choose another model."
        )

    def state_details(self) -> dict[str, JsonValue]:
        """What the failed turn's `session.state` event carries."""
        return {"code": self.code, "detail": str(self), **self.details}


class LocalModelNotFoundError(NotFoundError):
    def __init__(self, model_id: str) -> None:
        super().__init__(f"no local model {model_id!r}")


class LocalUnsupportedError(ConflictError):
    """What a local model cannot do, refused like an engine's missing feature (D113)."""

    code = "unsupported_feature"

    def __init__(self, feature: str, detail: str) -> None:
        self.feature = feature
        super().__init__(detail)

    def payload(self) -> dict[str, JsonValue]:
        return {
            "detail": str(self),
            "code": self.code,
            "provider": "local",
            "feature": self.feature,
        }


class AppNotInstalledError(NotFoundError):
    pass
