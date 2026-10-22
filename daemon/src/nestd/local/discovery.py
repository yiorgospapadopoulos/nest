"""Find on this Mac (B106): servers running on the apps' usual ports, and models downloaded
in the apps' folders that no running server serves. Nothing is installed or started.
"""

import asyncio
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import httpx

from nestd.local.memory import memory_warning
from nestd.local.models import DownloadedModel, FoundModel, StartApp
from nestd.local.probe import ProbedServer, normalise, probe
from nestd.local.weak import rate

# LM Studio, Ollama, llama.cpp (before and since 2026-10-09), vLLM and Lemonade, and
# KoboldCpp-style servers.
PORTS = (1234, 11434, 8080, 9931, 8000, 5001)
_HINTS = {
    "LM Studio": "Downloaded in LM Studio: start its server to use it.",
    "Ollama": "Downloaded with Ollama: start Ollama to use it.",
    "Hugging Face": (
        "In the Hugging Face cache: serve it with mlx-lm or llama.cpp, then enter its address."
    ),
    "llama.cpp": "In llama.cpp's cache: serve it with llama-server, then enter its address.",
}
_OLLAMA_REGISTRY = "registry.ollama.ai"
_SUFFIXES = (".gguf", "-gguf", "-mlx", ":latest")

type Which = Callable[[str], str | None]


@dataclass(frozen=True)
class ModelFolders:
    lmstudio_models: Path
    # LM Studio's command line, which starts its server.
    lms: Path
    ollama_models: Path
    huggingface_hub: Path
    llama_cpp: Path

    @classmethod
    def default(cls, home: Path, env: Mapping[str, str]) -> Self:
        hf_home = Path(env.get("HF_HOME") or home / ".cache" / "huggingface")
        return cls(
            lmstudio_models=home / ".lmstudio" / "models",
            lms=home / ".lmstudio" / "bin" / "lms",
            ollama_models=Path(env.get("OLLAMA_MODELS") or home / ".ollama" / "models"),
            huggingface_hub=Path(env.get("HF_HUB_CACHE") or hf_home / "hub"),
            llama_cpp=home / "Library" / "Caches" / "llama.cpp",
        )


async def running(client: httpx.AsyncClient) -> list[ProbedServer]:
    """The servers answering on this Mac's usual ports, in port order."""
    found = await asyncio.gather(
        *(probe(client, normalise(f"127.0.0.1:{port}"), None) for port in PORTS)
    )
    return [server for server in found if server is not None]


def found_models(
    server: ProbedServer, added: Collection[tuple[str, str]], memory: int | None = None
) -> list[FoundModel]:
    """The server's models, rated; `added` holds the (address, model) pairs Nest has, and
    `memory` is this Mac's in bytes.
    """
    address = server.address.address
    found: list[FoundModel] = []
    for model in server.models:
        tools, reason = rate(
            name=model.model,
            params=model.params,
            context=model.context,
            tools=model.tools,
            app=server.app,
        )
        found.append(
            FoundModel(
                address=address,
                app=server.app,
                model=model.model,
                name=display_name(model.model),
                context=model.context,
                tools=tools,
                weak_reason=reason,
                vision=model.vision,
                thinking=model.thinking,
                added=(address, model.model) in added,
                memory_warning=memory_warning(model.size, memory),
            )
        )
    return found


def display_name(model: str) -> str:
    return model.rsplit("/", 1)[-1]


def downloaded(
    folders: ModelFolders,
    which: Which,
    served: Collection[str] = (),
    running_apps: Collection[str | None] = (),
) -> list[DownloadedModel]:
    """Models on disk, by app; one that a running server lists (`served`) is left out, and
    so is the folder of a running app, whose server lists every model it downloaded under
    names other than its folders'.
    """
    taken = {_key(model) for model in served}
    found: list[DownloadedModel] = []
    for source, name, path in _on_disk(folders):
        if source in running_apps or "embed" in name.lower() or _key(name) in taken:
            continue
        found.append(
            DownloadedModel(
                name=name,
                source=source,
                path=str(path),
                hint=_HINTS[source],
                start=_start(source, folders, which),
            )
        )
    return found


def _on_disk(folders: ModelFolders) -> Iterator[tuple[str, str, Path]]:
    for repo in _children(folders.lmstudio_models, depth=2):
        if any(repo.glob("*.gguf")) or (
            (repo / "config.json").is_file() and any(repo.glob("*.safetensors"))
        ):
            yield "LM Studio", repo.name, repo
    for tag in _children(folders.ollama_models / "manifests", depth=4, files=True):
        host, namespace, model = (
            tag.parent.parent.parent.name,
            tag.parent.parent.name,
            tag.parent.name,
        )
        if host != _OLLAMA_REGISTRY:
            name = f"{host}/{namespace}/{model}:{tag.name}"
        elif namespace != "library":
            name = f"{namespace}/{model}:{tag.name}"
        else:
            name = f"{model}:{tag.name}"
        yield "Ollama", name, tag
    for cached in _children(folders.huggingface_hub, depth=1):
        if cached.name.startswith("models--") and _language_model(cached / "snapshots"):
            org, _, name = cached.name.removeprefix("models--").partition("--")
            yield "Hugging Face", f"{org}/{name}", cached
    if folders.llama_cpp.is_dir():
        for model in sorted(folders.llama_cpp.glob("*.gguf")):
            yield "llama.cpp", model.stem, model


def _language_model(snapshots: Path) -> bool:
    """GGUF weights, or a config with safetensors weights as MLX and transformers keep
    them; the cache also holds other kinds of models, such as ONNX image models.
    """
    names = {entry.name for entry in snapshots.rglob("*")}
    return any(name.endswith(".gguf") for name in names) or (
        "config.json" in names and any(name.endswith(".safetensors") for name in names)
    )


def _children(root: Path, *, depth: int, files: bool = False) -> list[Path]:
    """The entries `depth` levels below `root`, sorted: folders, or files with `files`."""
    level = [root] if root.is_dir() else []
    for step in range(depth):
        last = step == depth - 1
        level = sorted(
            child
            for parent in level
            for child in parent.iterdir()
            if (child.is_file() if files and last else child.is_dir())
        )
    return level


def _start(source: str, folders: ModelFolders, which: Which) -> StartApp | None:
    if source == "LM Studio" and folders.lms.is_file():
        return "lmstudio"
    if source == "Ollama" and which("ollama") is not None:
        return "ollama"
    return None


def _key(name: str) -> str:
    """A name as the same model's other names compare: its last part, without the
    format suffixes the folders and servers add.
    """
    key = name.rsplit("/", 1)[-1].lower()
    for suffix in _SUFFIXES:
        key = key.removesuffix(suffix)
    return key
