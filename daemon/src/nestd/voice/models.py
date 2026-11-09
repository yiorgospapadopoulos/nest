"""The Whisper models voice input offers, and what the API says about it (B154)."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from nestd.platform.base import PlatformName

type VoiceModelId = Literal["tiny.en", "base.en", "small.en", "medium.en"]
type VoiceState = Literal["not_installed", "installing", "ready", "install_failed"]
# What an install is doing: fetching the engine's packages, or the model.
type InstallStep = Literal["packages", "model"]


@dataclass(frozen=True)
class VoiceModel:
    id: VoiceModelId
    label: str
    # The model's files, about, in MB.
    size_mb: int
    # The Hugging Face commit of Systran/faster-whisper-<id> Nest fetches, so a changed
    # upload is never picked up unseen.
    revision: str


# English only (user, 2026-11-09): the `.en` models are more accurate for it.
MODELS: tuple[VoiceModel, ...] = (
    VoiceModel("tiny.en", "Tiny", 75, "0d3d19a32d3338f10357c0889762bd8d64bbdeba"),
    VoiceModel("base.en", "Base", 145, "3d3d5dee26484f91867d81cb899cfcf72b96be6c"),
    VoiceModel("small.en", "Small", 485, "d1d751a5f8271d482d14ca55d9e2deeebbae577f"),
    VoiceModel("medium.en", "Medium", 1530, "a29b04bd15381511a9af671baec01072039215e3"),
)
# The engine's packages on disk, about, in MB (177 measured on macOS arm64).
ENGINE_MB = 180


def voice_model(model_id: VoiceModelId) -> VoiceModel:
    return next(entry for entry in MODELS if entry.id == model_id)


def default_model(platform: PlatformName) -> VoiceModelId:
    """Small on a Mac, which turned 7 s of speech into text in 2 to 4 s while busy; Base on
    Linux, about four times faster, for machines with less to spare (D183).
    """
    return "small.en" if platform == "macos" else "base.en"


class VoiceModelInfo(BaseModel):
    id: VoiceModelId
    label: str
    size_mb: int


class VoiceStatus(BaseModel):
    """`GET /api/voice`."""

    state: VoiceState
    # The model in use: the settings' choice, or this system's default.
    model: VoiceModelId
    default_model: VoiceModelId
    models: list[VoiceModelInfo]
    # What installing would fetch now, about, in MB; 0 when ready.
    download_mb: int
    # While installing.
    step: InstallStep | None = None
    # Why the last install failed, in plain words.
    detail: str | None = None


class Transcript(BaseModel):
    """`POST /api/voice/transcribe`: what was said, empty when nothing was heard."""

    text: str
