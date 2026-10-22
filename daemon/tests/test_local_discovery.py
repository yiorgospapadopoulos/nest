from pathlib import Path

import httpx

from nestd.local.discovery import PORTS, ModelFolders, downloaded, found_models, running
from nestd.local.models import DownloadedModel, FoundModel
from nestd.local.probe import ProbedModel, ProbedServer, ServerAddress
from tests.local_support import Network, lm_studio, ollama


def folders(root: Path) -> ModelFolders:
    return ModelFolders(
        lmstudio_models=root / "lmstudio" / "models",
        lms=root / "lmstudio" / "bin" / "lms",
        ollama_models=root / "ollama",
        huggingface_hub=root / "hf",
        llama_cpp=root / "llama.cpp",
    )


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    return path


def test_the_default_folders_follow_the_apps_and_their_variables(tmp_path: Path) -> None:
    home = tmp_path / "home"

    assert ModelFolders.default(home, {}) == ModelFolders(
        lmstudio_models=home / ".lmstudio" / "models",
        lms=home / ".lmstudio" / "bin" / "lms",
        ollama_models=home / ".ollama" / "models",
        huggingface_hub=home / ".cache" / "huggingface" / "hub",
        llama_cpp=home / "Library" / "Caches" / "llama.cpp",
    )
    moved = ModelFolders.default(
        home, {"OLLAMA_MODELS": "/m/ollama", "HF_HOME": "/m/hf", "HF_HUB_CACHE": ""}
    )
    assert (moved.ollama_models, moved.huggingface_hub) == (Path("/m/ollama"), Path("/m/hf/hub"))
    assert ModelFolders.default(home, {"HF_HUB_CACHE": "/c", "HF_HOME": "/m"}).huggingface_hub == (
        Path("/c")
    )


async def test_running_servers_are_found_on_the_known_ports() -> None:
    network = Network(lm_studio(), ollama())
    async with httpx.AsyncClient(transport=network.transport()) as client:
        servers = await running(client)

    assert [server.address.address for server in servers] == ["127.0.0.1:1234", "127.0.0.1:11434"]
    assert PORTS == (1234, 11434, 8080, 9931, 8000, 5001)


def test_a_model_too_big_for_this_mac_is_flagged() -> None:
    gb = 1024**3
    server = ProbedServer(
        ServerAddress("127.0.0.1:1234", "http://127.0.0.1:1234"),
        "LM Studio",
        True,
        True,
        True,
        (
            ProbedModel("big-32b", 65536, None, True, False, False, 20 * gb),
            ProbedModel("small-32b", 65536, None, True, False, False, 5 * gb),
        ),
    )

    found = found_models(server, (), memory=24 * gb)

    assert [model.memory_warning for model in found] == [
        "Needs about 20 GB of this Mac's 24 GB: other work may slow down or the Mac may stall.",
        None,
    ]
    assert [model.memory_warning for model in found_models(server, ())] == [None, None]


def test_found_models_are_rated_and_marked_when_added() -> None:
    server = ProbedServer(
        ServerAddress("127.0.0.1:11434", "http://127.0.0.1:11434"),
        "Ollama",
        True,
        True,
        True,
        (
            ProbedModel("qwen3:32b", 4096, 32.8, True, False, True),
            ProbedModel("qwen/qwen3-coder-30b", 65536, None, True, True, False),
        ),
    )

    assert found_models(server, {("127.0.0.1:11434", "qwen/qwen3-coder-30b")}) == [
        FoundModel(
            address="127.0.0.1:11434",
            app="Ollama",
            model="qwen3:32b",
            name="qwen3:32b",
            context=4096,
            tools="weak",
            weak_reason="Context of 4k is too small for an agent: set Ollama to 64k.",
            vision=False,
            thinking=True,
            added=False,
        ),
        FoundModel(
            address="127.0.0.1:11434",
            app="Ollama",
            model="qwen/qwen3-coder-30b",
            name="qwen3-coder-30b",
            context=65536,
            tools="good",
            weak_reason=None,
            vision=True,
            thinking=False,
            added=True,
        ),
    ]


def test_downloaded_models_are_found_in_each_apps_folder(tmp_path: Path) -> None:
    where = folders(tmp_path)
    touch(where.lms)
    touch(where.lmstudio_models / "lmstudio-community" / "Qwen3-8B-GGUF" / "q.gguf")
    touch(where.lmstudio_models / "mlx-community" / "Qwen3-32B-4bit" / "config.json")
    touch(where.lmstudio_models / "mlx-community" / "Qwen3-32B-4bit" / "m.safetensors")
    # Neither a model file nor an MLX folder, and an embedding model.
    touch(where.lmstudio_models / "someone" / "notes" / "README.md")
    touch(where.lmstudio_models / "nomic-ai" / "nomic-embed-text-v1.5-GGUF" / "e.gguf")
    touch(where.lmstudio_models / "stray-file")
    manifests = where.ollama_models / "manifests"
    touch(manifests / "registry.ollama.ai" / "library" / "qwen3" / "32b")
    touch(manifests / "registry.ollama.ai" / "jmorgan" / "coder" / "latest")
    touch(manifests / "hf.co" / "unsloth" / "Qwen3-GGUF" / "Q4_K_M")
    cached = where.huggingface_hub / "models--mlx-community--Qwen3-14B-4bit" / "snapshots" / "a"
    touch(cached / "config.json")
    touch(cached / "model.safetensors")
    # An empty stub, which has no snapshot files.
    (where.huggingface_hub / "models--orcarouter--Qwen3.8-27B" / "snapshots" / "a").mkdir(
        parents=True
    )
    (where.huggingface_hub / "datasets--x--y").mkdir(parents=True)
    touch(where.llama_cpp / "ggml-org_gemma-3-12b-it-GGUF_gemma-3-12b-it-Q4_K_M.gguf")
    touch(where.llama_cpp / "manifest.json")

    found = downloaded(where, which=lambda _name: None)

    def entry(name: str, source: str, path: Path, start: str | None = None) -> DownloadedModel:
        return DownloadedModel.model_validate(
            {
                "name": name,
                "source": source,
                "path": str(path),
                "hint": HINTS[source],
                "start": start,
            }
        )

    assert found == [
        entry(
            "Qwen3-8B-GGUF",
            "LM Studio",
            where.lmstudio_models / "lmstudio-community" / "Qwen3-8B-GGUF",
            "lmstudio",
        ),
        entry(
            "Qwen3-32B-4bit",
            "LM Studio",
            where.lmstudio_models / "mlx-community" / "Qwen3-32B-4bit",
            "lmstudio",
        ),
        entry(
            "hf.co/unsloth/Qwen3-GGUF:Q4_K_M",
            "Ollama",
            manifests / "hf.co/unsloth/Qwen3-GGUF/Q4_K_M",
        ),
        entry(
            "jmorgan/coder:latest",
            "Ollama",
            manifests / "registry.ollama.ai" / "jmorgan" / "coder" / "latest",
        ),
        entry(
            "qwen3:32b", "Ollama", manifests / "registry.ollama.ai" / "library" / "qwen3" / "32b"
        ),
        entry(
            "mlx-community/Qwen3-14B-4bit",
            "Hugging Face",
            where.huggingface_hub / "models--mlx-community--Qwen3-14B-4bit",
        ),
        entry(
            "ggml-org_gemma-3-12b-it-GGUF_gemma-3-12b-it-Q4_K_M",
            "llama.cpp",
            where.llama_cpp / "ggml-org_gemma-3-12b-it-GGUF_gemma-3-12b-it-Q4_K_M.gguf",
        ),
    ]


def test_ollama_can_be_started_when_it_is_installed(tmp_path: Path) -> None:
    where = folders(tmp_path)
    touch(where.ollama_models / "manifests" / "registry.ollama.ai" / "library" / "qwen3" / "8b")

    found = downloaded(
        where, which=lambda name: "/opt/homebrew/bin/ollama" if name == "ollama" else None
    )

    assert [(model.name, model.start) for model in found] == [("qwen3:8b", "ollama")]


def test_nothing_downloaded_finds_nothing(tmp_path: Path) -> None:
    assert downloaded(folders(tmp_path), which=lambda _name: None) == []


def test_a_model_a_server_serves_is_not_listed_again(tmp_path: Path) -> None:
    where = folders(tmp_path)
    touch(where.lmstudio_models / "lmstudio-community" / "Qwen3-Coder-30B-GGUF" / "q.gguf")
    touch(where.ollama_models / "manifests" / "registry.ollama.ai" / "library" / "qwen3" / "32b")
    touch(where.ollama_models / "manifests" / "registry.ollama.ai" / "library" / "gemma3" / "4b")

    found = downloaded(
        where, which=lambda _name: None, served={"qwen/qwen3-coder-30b", "qwen3:32b"}
    )

    assert [model.name for model in found] == ["gemma3:4b"]


def test_a_running_app_lists_its_own_downloads_so_its_folder_is_skipped(tmp_path: Path) -> None:
    # LM Studio's folder names differ from its server's ids (mlx-community/gpt-oss-20b-MXFP4
    # against openai/gpt-oss-20b), and its running server lists every model it downloaded.
    where = folders(tmp_path)
    touch(where.lmstudio_models / "mlx-community" / "gpt-oss-20b-MXFP4-Q8" / "q.gguf")
    touch(where.ollama_models / "manifests" / "registry.ollama.ai" / "library" / "gemma3" / "4b")

    found = downloaded(where, which=lambda _name: None, running_apps={"LM Studio"})

    assert [model.name for model in found] == ["gemma3:4b"]


def test_only_language_models_count_in_the_hugging_face_cache(tmp_path: Path) -> None:
    where = folders(tmp_path)
    face_swap = where.huggingface_hub / "models--ezioruan--inswapper_128.onnx" / "snapshots" / "a"
    touch(face_swap / "inswapper_128.onnx")
    mlx = where.huggingface_hub / "models--mlx-community--Qwen3-14B-4bit" / "snapshots" / "a"
    touch(mlx / "config.json")
    touch(mlx / "model.safetensors")
    touch(where.huggingface_hub / "models--unsloth--Qwen3-GGUF" / "snapshots" / "a" / "q.gguf")

    found = downloaded(where, which=lambda _name: None)

    assert [model.name for model in found] == ["mlx-community/Qwen3-14B-4bit", "unsloth/Qwen3-GGUF"]


HINTS = {
    "LM Studio": "Downloaded in LM Studio: start its server to use it.",
    "Ollama": "Downloaded with Ollama: start Ollama to use it.",
    "Hugging Face": (
        "In the Hugging Face cache: serve it with mlx-lm or llama.cpp, then enter its address."
    ),
    "llama.cpp": "In llama.cpp's cache: serve it with llama-server, then enter its address.",
}
