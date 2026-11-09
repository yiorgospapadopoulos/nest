"""Nest's voice worker (B154): run by the daemon with the voice environment's Python
(`python -I worker.py ...`), never imported by the daemon, whose environment has none of
these packages.

`download --model <id> --revision <commit> --into <folder>` fetches a model.
`serve --model-dir <folder> --threads <n>` loads it, says `{"ready": true}`, then answers
each line `{"path": "<wav>"}` with `{"text": ...}` or `{"error": ...}`, one line each, until
its input closes. Only these lines go to stdout; everything else the libraries print goes
to stderr.
"""

import argparse
import json
import os
import sys
import wave
from typing import Any, TextIO

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.utils import download_model


def _say(out: TextIO, message: dict[str, Any]) -> None:
    out.write(json.dumps(message) + "\n")
    out.flush()


def _read_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as recording:
        frames = recording.readframes(recording.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def _serve(model_dir: str, threads: int, out: TextIO) -> None:
    whisper = WhisperModel(
        model_dir, device="cpu", compute_type="int8", cpu_threads=threads, local_files_only=True
    )
    _say(out, {"ready": True})
    for line in sys.stdin:
        try:
            request = json.loads(line)
            segments, _ = whisper.transcribe(
                _read_wav(request["path"]),
                language="en",
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as error:  # any failure is that one recording's answer
            _say(out, {"error": f"{type(error).__name__}: {error}"})
        else:
            _say(out, {"text": text})


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download")
    download.add_argument("--model", required=True)
    download.add_argument("--revision", required=True)
    download.add_argument("--into", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--model-dir", required=True)
    serve.add_argument("--threads", type=int, required=True)
    args = parser.parse_args()
    # The answers keep the real stdout; anything a library prints lands in stderr.
    out = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    if args.command == "download":
        download_model(
            args.model, output_dir=args.into, revision=args.revision, use_auth_token=False
        )
        _say(out, {"done": True})
    else:
        _serve(args.model_dir, args.threads, out)


if __name__ == "__main__":
    main()
