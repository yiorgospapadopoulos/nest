"""The code editors a project can open in (D181), in the order Open in lists them, and where
each platform finds them. An editor is offered only when it is installed."""

from dataclasses import dataclass
from typing import Literal

type EditorId = Literal[
    "vscode",
    "cursor",
    "zed",
    "xcode",
    "idea",
    "pycharm",
    "webstorm",
    "goland",
    "rustrover",
    "clion",
    "phpstorm",
    "rubymine",
    "rider",
    "android-studio",
]


@dataclass(frozen=True)
class Editor:
    id: EditorId
    name: str
    # macOS app bundles, the usual one first; empty when there is no Mac version.
    mac_apps: tuple[str, ...]
    # Linux launch commands and flatpak ids, the usual one first; empty when there is none.
    linux_commands: tuple[str, ...]


def _jetbrains(id_: EditorId, name: str, command: str, flatpak: str) -> Editor:
    """A JetBrains IDE: its app, the command Toolbox or a snap installs, and the shell
    launcher of a tarball install."""
    return Editor(id_, name, (f"{name}.app",), (command, f"{command}.sh", flatpak))


EDITORS: tuple[Editor, ...] = (
    Editor("vscode", "VS Code", ("Visual Studio Code.app",), ("code", "com.visualstudio.code")),
    Editor("cursor", "Cursor", ("Cursor.app",), ("cursor",)),
    Editor("zed", "Zed", ("Zed.app", "Zed Preview.app"), ("zed", "zeditor", "dev.zed.Zed")),
    Editor("xcode", "Xcode", ("Xcode.app", "Xcode-beta.app"), ()),
    Editor(
        "idea",
        "IntelliJ IDEA",
        ("IntelliJ IDEA.app", "IntelliJ IDEA Ultimate.app", "IntelliJ IDEA CE.app"),
        (
            "idea",
            "intellij-idea-ultimate",
            "intellij-idea-community",
            "idea.sh",
            "com.jetbrains.IntelliJ-IDEA-Ultimate",
            "com.jetbrains.IntelliJ-IDEA-Community",
        ),
    ),
    Editor(
        "pycharm",
        "PyCharm",
        ("PyCharm.app", "PyCharm Professional Edition.app", "PyCharm CE.app"),
        (
            "pycharm",
            "pycharm-professional",
            "pycharm-community",
            "pycharm.sh",
            "com.jetbrains.PyCharm-Professional",
            "com.jetbrains.PyCharm-Community",
        ),
    ),
    _jetbrains("webstorm", "WebStorm", "webstorm", "com.jetbrains.WebStorm"),
    _jetbrains("goland", "GoLand", "goland", "com.jetbrains.GoLand"),
    _jetbrains("rustrover", "RustRover", "rustrover", "com.jetbrains.RustRover"),
    _jetbrains("clion", "CLion", "clion", "com.jetbrains.CLion"),
    _jetbrains("phpstorm", "PhpStorm", "phpstorm", "com.jetbrains.PhpStorm"),
    _jetbrains("rubymine", "RubyMine", "rubymine", "com.jetbrains.RubyMine"),
    _jetbrains("rider", "Rider", "rider", "com.jetbrains.Rider"),
    Editor(
        "android-studio",
        "Android Studio",
        ("Android Studio.app",),
        ("android-studio", "studio", "studio.sh", "com.google.AndroidStudio"),
    ),
)

EDITORS_BY_ID: dict[EditorId, Editor] = {editor.id: editor for editor in EDITORS}


def default_editor(installed: list[Editor], chosen: EditorId | None) -> Editor | None:
    """The chosen editor while it is installed, else the first installed one."""
    for editor in installed:
        if editor.id == chosen:
            return editor
    return installed[0] if installed else None
