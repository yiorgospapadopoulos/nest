"""Voice input (B154): speech to text with a local Whisper model, for the phone and the
Linux app."""

from fastapi import APIRouter, Request, status

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_voice
from nestd.config.models import VoiceSettings
from nestd.errors import ConflictError, InvalidInputError
from nestd.voice.audio import MAX_BYTES, MAX_SECONDS
from nestd.voice.models import Transcript, VoiceStatus

router = APIRouter(prefix="/api/voice", dependencies=[RequireDevice])


@router.get("")
async def voice_status(ctx: Context) -> VoiceStatus:
    return ctx.voice.status()


@router.post("/install", status_code=status.HTTP_202_ACCEPTED)
async def install_voice(ctx: Context) -> VoiceStatus:
    """Fetch the engine and the chosen model in the background (about 0.3 to 1.7 GB);
    `GET /api/voice` follows it.
    """
    return ctx.voice.start_install()


@router.delete("")
async def remove_voice(ctx: Context) -> VoiceStatus:
    """Delete the engine and its models; 409 while they are being fetched."""
    return await ctx.voice.remove()


@router.get("/settings")
async def get_voice_settings(ctx: Context) -> VoiceSettings:
    return ctx.settings.voice


@router.put("/settings")
async def put_voice_settings(body: VoiceSettings, ctx: Context) -> VoiceStatus:
    """Replace the `[voice]` section of settings.toml; a new model is fetched by the next
    install; 409 while one runs.
    """
    ctx.voice.check_model_change()
    try:
        saved = save_voice(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"voice": saved})
    await ctx.voice.model_changed()
    return ctx.voice.status()


@router.post("/transcribe")
async def transcribe(request: Request, ctx: Context) -> Transcript:
    """The body is a WAV recording, 16-bit PCM, one channel at 16 kHz, at most 5 minutes:
    422 for anything else, 409 before voice input is set up, 502 when the engine fails.
    """
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            msg = f"recordings are at most {MAX_SECONDS // 60} minutes"
            raise InvalidInputError(msg)
    return Transcript(text=await ctx.voice.transcribe(bytes(body)))
